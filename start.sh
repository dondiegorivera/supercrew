#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

prompt="${*:-}"

if [[ -n "${prompt}" ]]; then
  export TASK_TEXT="${prompt}"
fi

docker compose run --rm --build \
  -e TASK_TEXT="${TASK_TEXT:-}" \
  -e SCENARIO="${SCENARIO:-}" \
  -e CREW_TEMPLATE="${CREW_TEMPLATE:-}" \
  -e TOPIC="${TOPIC:-}" \
  crewai
