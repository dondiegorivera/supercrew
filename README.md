# Supercrew

A dynamic wrapper around [CrewAI](https://docs.crewai.com) that builds the right crew for your task automatically. Give it a plain-English task and it will reuse a known crew, adapt one, or generate a new crew from scratch. You can also pin an existing crew for deterministic execution.

## How it works

```
You: ./start.sh "find jazz festivals in Berlin summer 2026"

Supercrew:
  1. Sends your task to a cloud LLM (via LiteLLM)
  2. LLM reuses, adapts, or generates a crew
  3. CrewAI agents execute the crew (search, analyze, synthesize)
  4. Result is saved to outputs/ (or /tmp/agent_mesh_outputs if needed)
```

Three models work together through a single LiteLLM proxy:

| Model | Size | Role |
|-------|------|------|
| `cloud-fast` | Cloud | Smartest. Plans crews, complex synthesis |
| `local-clever` | 27B local | Analysis, auditing, reasoning |
| `local-swarm` | 9B local | Parallel research workers (up to 16 concurrent). Vision. |

## Quick start

```bash
# 1. Copy and fill in your environment
cp .env.example .env
# Edit .env with your LiteLLM proxy URL and API key

# 2. Run with a task
./start.sh "compare the top 3 project management tools for a small team"

# Or use an existing crew directly (skips the planner)
./start.sh --crew research --effort quick "music festivals in Barcelona 2026"

# Control how much effort agents put in
./start.sh --effort thorough "find all outdoor cinema events in Amsterdam"

# Force a brand-new generated crew
./start.sh --new --effort standard "find trödelmärkte in Kreis Steinfurt in April and May 2026"

# Force HTML artifact saving
./start.sh --format html "create a standalone HTML landing page for a Berlin jazz guide"

# Save a generated crew for reuse
./start.sh --save event_scout "weekend events in Munich"

# Read task from a file
./start.sh --input input.md

# Promote a good generated crew into config/crews/
./start.sh --promote event_scout
```

## CLI flags

| Flag | Purpose |
|------|---------|
| `--crew NAME` | Run a specific existing crew and skip planner selection |
| `--effort LEVEL` | Override the effort profile for the run |
| `--format TYPE` | Output artifact format: `auto`, `text`, or `html`; `html` also nudges the planner toward a dedicated final HTML-writing step |
| `--save NAME` | Save the planner-generated crew for later reuse |
| `--input FILE` | Read task text from a file |
| `--promote NAME` | Promote a generated crew into `config/crews/` |
| `--new` | Force the planner to start from scratch and generate a new crew |

## Effort levels

| Level | Agents | Iterations | Use when |
|-------|--------|-----------|----------|
| `quick` | 2-3 | 5 | Simple question, fast lookup |
| `standard` | 3-4 | 15 | Normal research (default) |
| `thorough` | 4-6 | 25 | Deep research, verification |
| `exhaustive` | 5-8 | 40 | Maximum coverage, multi-source |

## Pre-built crews

| Crew | Agents | What it does |
|------|--------|-------------|
| `research` | 3 | Web search + analysis + writing |
| `deep_research` | 7 | Multi-source research with coverage audit and evidence normalization |
| `deep_research_cloud_review` | 7 | Deep research with cloud-powered final review |
| `parallel_research` | 5 | Parallel fact/pricing/risk branches merged by analyst |
| `analysis` | 2 | Reasoning over provided material |
| `synthesis` | 2 | Merge and polish scattered input |

## Project structure

```
start.sh                     Entry point
supercrew.py                 Python entry point (called by Docker)
config/
  models.yaml                LLM model profiles (swarm, clever, cloud_fast)
  tools.yaml                 Tool definitions (search, web fetch, PDF)
  effort.yaml                Effort level settings
  model_policy.yaml          Model assignment guidelines for the planner
  routing.yaml               Keyword-based routing fallback
  crew_registry.yaml         Crew metadata index
  planner_handbook.md        Rules for the planner LLM
  crews/                     Hand-authored crew definitions (YAML)
  generated_crews/           Planner-created crews (auto-saved)
  catalogs/                  Building blocks (role archetypes, task patterns)
  scenarios/                 Predefined run configurations
src/agent_mesh/
  runner.py                  Main dispatch logic
  planner.py                 Dynamic crew planning via cloud LLM
  crew_builder.py            Instantiate CrewAI Crew from config
  agent_factory.py           Instantiate CrewAI Agents from config
  crew_spec.py               Pydantic models for crew specifications
  crew_renderer.py           Render crew specs to YAML
  registry.py                Crew registry (load, match, track usage)
  config_loader.py           YAML config loading
  llm_registry.py            LLM profile management
  tools.py                   Custom tools (SearXNG, Crawl4AI, PDF)
  compat.py                  LiteLLM message sanitizer
```

## Requirements

- Docker (the crew runs inside a container)
- A LiteLLM proxy serving your models
- SearXNG instance (for web search tool)
- Crawl4AI instance (for web page fetching)

## Environment variables

Set these in `.env`:

```bash
# Required
LITELLM_BASE_URL=http://your-litellm-proxy:4000/v1
LITELLM_API_KEY=your-key

# Required for search
SEARXNG_BASE_URL=http://your-searxng:8080

# Optional
CRAWL4AI_BASE_URL=https://your-crawl4ai-instance
EFFORT=standard              # Default effort level
PLANNER_DISABLED=0           # Set to 1 to skip planner, use keyword routing
FORCE_GENERATE=0             # Set to 1 to force planner generation from scratch
OUTPUT_FORMAT=auto           # auto | text | html
```

## Make targets

```bash
make build    # Build the Docker image
make run      # Run with PROMPT plus optional CREW/EFFORT/SAVE/INPUT/OUTPUT_FORMAT
make run-new  # Force planner generation from scratch
make promote  # Promote a generated crew via PROMOTE=name
make test     # Compile-check Python files and validate start.sh syntax
make shell    # Open a shell with .env loaded
make up       # Start services in background
make down     # Stop services
make logs     # Tail logs
```

Examples:

```bash
make run PROMPT="compare the top 3 note-taking apps"
make run CREW=research EFFORT=quick PROMPT="find jazz festivals in Berlin 2026"
make run OUTPUT_FORMAT=html PROMPT="create a standalone HTML landing page for a Berlin jazz guide"
make run-new EFFORT=standard PROMPT="find trödelmärkte in Kreis Steinfurt in April and May 2026"
make promote PROMOTE=event_scout
```

## How the planner works

When you run a task without specifying `--crew`, the planner:

1. Extracts features from your task text
2. Checks the crew registry for existing crews that match
3. Calls `cloud-fast` with the task, candidate crews, and building-block catalogs
4. The LLM decides: **reuse** an existing crew, **adapt** one, or **generate** a new one
5. Generated crews are validated against strict rules before execution
6. New crews are saved to `config/generated_crews/` for future reuse

If the planner fails for any reason, the system falls back to keyword-based routing.
If you want to bypass reuse and adaptation for a run, use `--new`.

## Output files

Every run writes:

- `outputs/latest.txt`
- `outputs/latest.json`

If the result looks like HTML, or you explicitly set `--format html` / `OUTPUT_FORMAT=html`, the runtime also writes:

- `outputs/latest.html`

Timestamped per-run files follow the same behavior.
When `html` is requested explicitly, the planner is also nudged to generate a final writer-oriented task that outputs standalone HTML.

## HTML output

If you want an HTML deliverable, use one of these:

```bash
./start.sh --format html "create a standalone HTML landing page for a Berlin jazz guide"
OUTPUT_FORMAT=html ./start.sh "summarize these findings as a standalone HTML report"
```

What to expect:

- The planner is nudged to generate a final writer/presentation step aimed at standalone HTML.
- The final artifact is still printed to stdout.
- The runtime saves `outputs/latest.html` in addition to `outputs/latest.txt` and `outputs/latest.json`.

If you leave the format at `auto`, the runtime will still save `.html` when the final answer already looks like HTML.

## Crew lifecycle

```
Generated crew  -->  Use it a few times  -->  Promote to config/crews/
                                               (./start.sh --promote name)
```

Generated crews accumulate usage stats in the registry. Promote the good ones
to hand-authored status for long-term use.

## Docs

| Document | Purpose |
|----------|---------|
| `docs/specs/architecture.md` | Full architecture specification |
| `docs/sprints/feature-sprints.md` | Sprint plans for implementation |
| `docs/crewai/` | CrewAI framework reference docs |
| `AGENTS.md` | Multi-agent framework conventions |
| `CLAUDE.md` | Architect agent instructions |
| `CODEX.md` | Coder agent instructions |
