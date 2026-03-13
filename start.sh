#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Defaults
crew=""
effort=""
save_name=""
input_file=""
promote_name=""
force_generate="0"
positional_args=()

# Parse flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --crew)
      crew="$2"
      shift 2
      ;;
    --effort)
      effort="$2"
      shift 2
      ;;
    --save)
      save_name="$2"
      shift 2
      ;;
    --input)
      input_file="$2"
      shift 2
      ;;
    --promote)
      promote_name="$2"
      shift 2
      ;;
    --new)
      force_generate="1"
      shift
      ;;
    *)
      positional_args+=("$1")
      shift
      ;;
  esac
done

prompt="${positional_args[*]:-}"

if [[ -n "${promote_name}" ]]; then
  python_cmd="python3"
  if [[ -x ".venv/bin/python" ]]; then
    python_cmd=".venv/bin/python"
  fi

  "${python_cmd}" - <<'PY' "${promote_name}"
import sys

sys.path.insert(0, "src")

from agent_mesh.registry import CrewRegistry

name = sys.argv[1]
registry = CrewRegistry()
registry.load()
path = registry.promote(name)
if path is None:
    raise SystemExit(f"Unable to promote crew: {name}")
registry.save()
print(f"Promoted {name} -> {path}")
PY
  exit 0
fi

if [[ -n "${prompt}" ]]; then
  export TASK_TEXT="${prompt}"
fi

host_uid="$(id -u)"
host_gid="$(id -g)"
export LOCAL_UID="${host_uid}"
export LOCAL_GID="${host_gid}"

docker compose run --rm --build \
  --user "${host_uid}:${host_gid}" \
  -e TASK_TEXT="${TASK_TEXT:-${prompt}}" \
  -e SCENARIO="${SCENARIO:-}" \
  -e CREW_TEMPLATE="${crew:-${CREW_TEMPLATE:-}}" \
  -e TOPIC="${TOPIC:-}" \
  -e EFFORT="${effort:-${EFFORT:-standard}}" \
  -e CREW_SAVE_NAME="${save_name:-${CREW_SAVE_NAME:-}}" \
  -e INPUT_FILE="${input_file:-${INPUT_FILE:-}}" \
  -e PLANNER_DISABLED="${PLANNER_DISABLED:-0}" \
  -e FORCE_GENERATE="${force_generate:-${FORCE_GENERATE:-0}}" \
  -e LOCAL_UID="${host_uid}" \
  -e LOCAL_GID="${host_gid}" \
  crewai
