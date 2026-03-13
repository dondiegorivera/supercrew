#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Defaults
crew=""
effort=""
save_name=""
input_file=""
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
    *)
      positional_args+=("$1")
      shift
      ;;
  esac
done

prompt="${positional_args[*]:-}"

if [[ -n "${prompt}" ]]; then
  export TASK_TEXT="${prompt}"
fi

docker compose run --rm --build \
  -e TASK_TEXT="${TASK_TEXT:-${prompt}}" \
  -e SCENARIO="${SCENARIO:-}" \
  -e CREW_TEMPLATE="${crew:-${CREW_TEMPLATE:-}}" \
  -e TOPIC="${TOPIC:-}" \
  -e EFFORT="${effort:-${EFFORT:-standard}}" \
  -e CREW_SAVE_NAME="${save_name:-${CREW_SAVE_NAME:-}}" \
  -e INPUT_FILE="${input_file:-${INPUT_FILE:-}}" \
  -e PLANNER_DISABLED="${PLANNER_DISABLED:-0}" \
  crewai
