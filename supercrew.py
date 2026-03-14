from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

for env_var, default in [
    ("HOME", "/tmp/crewai-home"),
    ("XDG_DATA_HOME", "/tmp/crewai-home/.local/share"),
    ("XDG_CACHE_HOME", "/tmp/crewai-home/.cache"),
    ("XDG_CONFIG_HOME", "/tmp/crewai-home/.config"),
]:
    path = Path(os.environ.get(env_var, default))
    path.mkdir(parents=True, exist_ok=True)

if not os.environ.get("OPENAI_API_KEY"):
    litellm_api_key = os.environ.get("LITELLM_API_KEY")
    if litellm_api_key:
        os.environ["OPENAI_API_KEY"] = litellm_api_key

if not os.environ.get("OPENAI_BASE_URL"):
    litellm_base_url = os.environ.get("LITELLM_BASE_URL")
    if litellm_base_url:
        os.environ["OPENAI_BASE_URL"] = litellm_base_url
        os.environ.setdefault("OPENAI_API_BASE", litellm_base_url)


def _resolve_output_dir() -> Path:
    preferred = Path(os.getenv("OUTPUT_DIR", "outputs"))
    for candidate in (preferred, Path("/tmp/agent_mesh_outputs")):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise OSError("No writable output directory available.")


def _normalize_output_format(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"html", "text", "auto"}:
        return candidate
    return "auto"


def _suppress_crewai_trace_prompts() -> None:
    try:
        from crewai.events.listeners.tracing.utils import set_suppress_tracing_messages

        set_suppress_tracing_messages(True)
    except Exception:
        return


def _unwrap_html_fence(result_text: str) -> str:
    stripped = result_text.strip()
    match = re.fullmatch(r"```(?:html)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return result_text


def _looks_like_html(result_text: str) -> bool:
    snippet = _unwrap_html_fence(result_text).strip().lower()
    if snippet.startswith("<!doctype html") or snippet.startswith("<html"):
        return True
    return (
        any(tag in snippet for tag in ("<body", "<head", "<main", "<article", "<section"))
        and "</" in snippet
        and "<" in snippet
    )


def _should_save_html(result_text: str, output_format: str) -> bool:
    if output_format == "html":
        return True
    if output_format == "text":
        return False
    return _looks_like_html(result_text)


def _write_text_file(path: Path, content: str) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _write_result_files(
    output_dir: Path,
    *,
    timestamp: str,
    scenario: str,
    result_text: str,
    task_text: str | None,
    output_format: str,
) -> Path:
    text_path = output_dir / f"{timestamp}_{scenario}.txt"
    latest_text_path = output_dir / "latest.txt"
    json_path = output_dir / f"{timestamp}_{scenario}.json"
    latest_json_path = output_dir / "latest.json"

    _write_text_file(text_path, result_text)
    _write_text_file(latest_text_path, result_text)

    payload = {
        "timestamp": timestamp,
        "scenario": scenario,
        "task_text": task_text,
        "result": result_text,
        "output_format": "html" if _should_save_html(result_text, output_format) else "text",
    }
    serialized = json.dumps(payload, ensure_ascii=True, indent=2)
    _write_text_file(json_path, serialized)
    _write_text_file(latest_json_path, serialized)

    if _should_save_html(result_text, output_format):
        html_text = _unwrap_html_fence(result_text)
        html_path = output_dir / f"{timestamp}_{scenario}.html"
        latest_html_path = output_dir / "latest.html"
        _write_text_file(html_path, html_text)
        _write_text_file(latest_html_path, html_text)
        return html_path

    return text_path


def _save_result(result: object) -> Path | None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_text = str(result)
    scenario = os.getenv("SCENARIO", "smoke")
    task_text = os.getenv("TASK_TEXT") or os.getenv("TOPIC")
    output_format = _normalize_output_format(os.getenv("OUTPUT_FORMAT"))

    try:
        output_dir = _resolve_output_dir()
    except OSError:
        return None

    try:
        return _write_result_files(
            output_dir,
            timestamp=timestamp,
            scenario=scenario,
            result_text=result_text,
            task_text=task_text,
            output_format=output_format,
        )
    except OSError:
        return None


def main() -> None:
    from agent_mesh.runner import run_from_env

    _suppress_crewai_trace_prompts()
    result = run_from_env()
    saved_path = _save_result(result)

    print("\n=== FINAL RESULT ===\n")
    print(result)
    if saved_path is not None:
        print(f"\n=== SAVED TO ===\n{saved_path}")


if __name__ == "__main__":
    main()
