from __future__ import annotations

from io import BytesIO
import os
import json
from typing import Any
from urllib.parse import urlparse

from pypdf import PdfReader
import requests
from crewai.tools import BaseTool


class SearxngSearchTool(BaseTool):
    name: str = "SearXNG Search"
    description: str = (
        "Search the web using a private SearXNG instance and return concise results "
        "with titles, URLs, snippets, and metadata. Use this multiple times with focused queries "
        "to expand coverage and avoid missing relevant candidates."
    )

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        max_results: int = 8,
        max_queries: int = 4,
        max_snippet_chars: int = 220,
    ) -> None:
        super().__init__()
        self._base_url = base_url
        self._api_key = api_key
        self._max_results = max_results
        self._max_queries = max_queries
        self._max_snippet_chars = max_snippet_chars

    def _run(self, query: str) -> str:
        url = f"{self._base_url.rstrip('/')}/search"
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        queries = [line.strip() for line in query.splitlines() if line.strip()]
        if not queries:
            return "No search query provided."

        combined_blocks: list[str] = []
        for block_index, single_query in enumerate(queries[: self._max_queries], start=1):
            response = requests.get(
                url,
                params={"q": single_query, "format": "json"},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()

            results = payload.get("results", [])[: self._max_results]
            if not results:
                combined_blocks.append(f"Query {block_index}: {single_query}\nNo search results returned.\n")
                continue

            lines: list[str] = [f"Query {block_index}: {single_query}"]
            for index, result in enumerate(results, start=1):
                title = result.get("title", "").strip()
                link = result.get("url", "").strip()
                content = result.get("content", "").strip()[: self._max_snippet_chars]
                engine = str(result.get("engine", "")).strip()
                published = str(result.get("publishedDate") or result.get("published_date") or "").strip()
                extra = []
                if engine:
                    extra.append(f"Engine: {engine}")
                if published:
                    extra.append(f"Published: {published}")
                detail_block = "\n".join(extra)
                if detail_block:
                    detail_block = f"\n{detail_block}"
                lines.append(f"{index}. {title}\nURL: {link}\nSnippet: {content}{detail_block}\n")

            combined_blocks.append("\n".join(lines))

        return "\n\n".join(combined_blocks)


class Crawl4AIMarkdownTool(BaseTool):
    name: str = "Crawl4AI Markdown Fetch"
    description: str = (
        "Fetch a page through the Crawl4AI service and return compact markdown. "
        "Input can be just a URL, or multiple lines with the first line as the URL and the remaining lines "
        "as a focus query for the crawler."
    )

    def __init__(self, base_url: str, markdown_filter: str = "fit", max_chars: int = 12000) -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._markdown_filter = markdown_filter
        self._max_chars = max_chars

    def _parse_input(self, tool_input: str) -> tuple[str, str | None]:
        lines = [line.strip() for line in tool_input.splitlines() if line.strip()]
        if not lines:
            return "", None
        url = lines[0]
        if url.lower().startswith("url:"):
            url = url.split(":", 1)[1].strip()
        query: str | None = None
        if len(lines) > 1:
            remainder = lines[1:]
            if remainder[0].lower().startswith("query:"):
                remainder[0] = remainder[0].split(":", 1)[1].strip()
            query = "\n".join(part for part in remainder if part).strip() or None
        return url, query

    def _run(self, tool_input: str) -> str:
        url, query = self._parse_input(tool_input)
        if not url.startswith("http://") and not url.startswith("https://"):
            return "Invalid URL. Provide a full http:// or https:// URL."

        payload: dict[str, Any] = {
            "url": url,
            "f": self._markdown_filter,
        }
        if query:
            payload["q"] = query

        response = requests.post(
            f"{self._base_url}/md",
            timeout=30,
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        markdown = (
            data.get("markdown")
            or data.get("fit_markdown")
            or data.get("raw_markdown")
            or data.get("result")
            or ""
        )
        if isinstance(markdown, dict):
            markdown = json.dumps(markdown, ensure_ascii=True)
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = json.dumps(data, ensure_ascii=True)

        return (
            f"URL: {data.get('url', url)}\n"
            f"Filter: {data.get('filter', self._markdown_filter)}\n"
            f"Success: {data.get('success', True)}\n\n"
            f"{markdown[: self._max_chars]}"
        )


def _resolve_pdf_storage_dir(preferred_dir: str) -> str:
    candidate_dirs = [preferred_dir, "/tmp/agent_mesh_pdfs"]
    for directory in candidate_dirs:
        try:
            os.makedirs(directory, exist_ok=True)
            probe_path = os.path.join(directory, ".write_test")
            with open(probe_path, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe_path)
            return directory
        except OSError:
            continue
    raise OSError("No writable PDF storage directory available.")


def _download_pdf_bytes(source: str, timeout_seconds: int, max_bytes: int) -> tuple[bytes, str]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(
            source,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (compatible; crewai-test/1.0; +https://example.invalid)"},
        )
        response.raise_for_status()
        content = response.content
        if len(content) > max_bytes:
            raise ValueError(f"PDF exceeds max_bytes limit ({max_bytes}).")
        content_type = response.headers.get("content-type", "")
        if not source.lower().endswith(".pdf") and "pdf" not in content_type.lower():
            raise ValueError("Source does not look like a PDF by URL or content type.")
        return content, response.url

    with open(source, "rb") as handle:
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"PDF exceeds max_bytes limit ({max_bytes}).")
    return content, source


def _parse_pdf_tool_input(tool_input: str) -> tuple[str, str | None]:
    lines = [line.strip() for line in tool_input.splitlines() if line.strip()]
    if not lines:
        return "", None
    source = lines[0]
    if source.lower().startswith("source:"):
        source = source.split(":", 1)[1].strip()
    query: str | None = None
    if len(lines) > 1:
        remainder = lines[1:]
        if remainder[0].lower().startswith("query:"):
            remainder[0] = remainder[0].split(":", 1)[1].strip()
        query = "\n".join(part for part in remainder if part).strip() or None
    return source, query


class PDFFetchTool(BaseTool):
    name: str = "PDF Fetch"
    description: str = (
        "Download a PDF from a URL or copy a local PDF into a writable working directory. "
        "Use this when a search result points to a brochure, schedule, program, or ticket PDF."
    )

    def __init__(self, storage_dir: str, timeout_seconds: int = 45, max_bytes: int = 20_000_000) -> None:
        super().__init__()
        self._storage_dir = _resolve_pdf_storage_dir(storage_dir)
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def _run(self, source: str) -> str:
        source = source.strip()
        if not source:
            return "Provide a PDF URL or local PDF path."

        content, resolved_source = _download_pdf_bytes(
            source=source,
            timeout_seconds=self._timeout_seconds,
            max_bytes=self._max_bytes,
        )
        parsed = urlparse(resolved_source)
        filename = os.path.basename(parsed.path) or "document.pdf"
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        output_path = os.path.join(self._storage_dir, filename)
        counter = 1
        stem, ext = os.path.splitext(output_path)
        while os.path.exists(output_path):
            output_path = f"{stem}_{counter}{ext}"
            counter += 1
        with open(output_path, "wb") as handle:
            handle.write(content)

        return (
            f"Saved PDF\n"
            f"Source: {resolved_source}\n"
            f"Path: {output_path}\n"
            f"Bytes: {len(content)}"
        )


class PDFExtractTool(BaseTool):
    name: str = "PDF Extract"
    description: str = (
        "Extract readable text from a PDF URL or local PDF path. "
        "Input can be a single source line, or a source plus an optional query on later lines."
    )

    def __init__(
        self,
        timeout_seconds: int = 45,
        max_bytes: int = 20_000_000,
        max_pages: int = 8,
        max_chars: int = 6000,
    ) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._max_chars = max_chars

    def _run(self, tool_input: str) -> str:
        source, query = _parse_pdf_tool_input(tool_input)
        if not source:
            return "Provide a PDF URL or local PDF path."

        content, resolved_source = _download_pdf_bytes(
            source=source,
            timeout_seconds=self._timeout_seconds,
            max_bytes=self._max_bytes,
        )
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                return f"Encrypted PDF could not be decrypted: {exc}"

        query_terms = []
        if query:
            query_terms = [term.lower() for term in query.replace(",", " ").split() if term.strip()]

        excerpts: list[str] = []
        for page_index, page in enumerate(reader.pages[: self._max_pages], start=1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception:
                page_text = ""
            if not page_text:
                continue
            page_text = " ".join(page_text.split())
            if query_terms:
                snippets = [
                    sentence.strip()
                    for sentence in page_text.split(". ")
                    if any(term in sentence.lower() for term in query_terms)
                ]
                if snippets:
                    page_text = ". ".join(snippets)
            page_excerpt = page_text[:1200].strip()
            if page_excerpt:
                excerpts.append(f"[Page {page_index}] {page_excerpt}")
            if len("\n\n".join(excerpts)) >= self._max_chars:
                break

        combined = "\n\n".join(excerpts)[: self._max_chars].strip()
        if not combined:
            combined = "No extractable text found in the first pages of this PDF."

        return (
            f"PDF Source: {resolved_source}\n"
            f"Pages: {len(reader.pages)}\n"
            f"Query: {query or 'none'}\n\n"
            f"{combined}"
        )


def build_tool_registry(config: dict[str, Any]) -> dict[str, BaseTool]:
    defaults = config.get("defaults", {})
    tools_config = config.get("tools", {})

    base_url = os.getenv(
        defaults.get("searxng_base_url_env", "SEARXNG_BASE_URL"),
        defaults.get("searxng_base_url", "http://100.80.49.81:8080"),
    )
    api_key = os.getenv(
        defaults.get("searxng_api_key_env", "SEARXNG_API_KEY"),
        defaults.get("searxng_api_key", ""),
    )
    crawl4ai_base_url = os.getenv(
        defaults.get("crawl4ai_base_url_env", "CRAWL4AI_BASE_URL"),
        defaults.get("crawl4ai_base_url", "https://agentgym.tail1ded0f.ts.net"),
    )
    crawl4ai_markdown_filter = defaults.get("crawl4ai_markdown_filter", "fit")
    pdf_storage_dir = os.getenv(
        defaults.get("pdf_storage_dir_env", "PDF_STORAGE_DIR"),
        defaults.get("pdf_storage_dir", "outputs/pdfs"),
    )

    registry: dict[str, BaseTool] = {}
    for name, tool_spec in tools_config.items():
        if not tool_spec.get("enabled", True):
            continue
        class_name = tool_spec.get("class_name")
        if class_name == "SearxngSearchTool":
            registry[name] = SearxngSearchTool(
                base_url=base_url,
                api_key=api_key,
                max_results=int(tool_spec.get("max_results", 8)),
                max_queries=int(tool_spec.get("max_queries", 4)),
                max_snippet_chars=int(tool_spec.get("max_snippet_chars", 220)),
            )
            continue
        if class_name == "Crawl4AIMarkdownTool":
            registry[name] = Crawl4AIMarkdownTool(
                base_url=crawl4ai_base_url,
                markdown_filter=str(tool_spec.get("markdown_filter", crawl4ai_markdown_filter)),
                max_chars=int(tool_spec.get("max_chars", 12000)),
            )
            continue
        if class_name == "PDFFetchTool":
            registry[name] = PDFFetchTool(
                storage_dir=pdf_storage_dir,
                timeout_seconds=int(tool_spec.get("timeout_seconds", 45)),
                max_bytes=int(tool_spec.get("max_bytes", 20_000_000)),
            )
            continue
        if class_name == "PDFExtractTool":
            registry[name] = PDFExtractTool(
                timeout_seconds=int(tool_spec.get("timeout_seconds", 45)),
                max_bytes=int(tool_spec.get("max_bytes", 20_000_000)),
                max_pages=int(tool_spec.get("max_pages", 8)),
                max_chars=int(tool_spec.get("max_chars", 6000)),
            )
            continue
        raise ValueError(f"Unsupported tool class: {class_name}")

    return registry
