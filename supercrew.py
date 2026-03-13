from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent_mesh.runner import run_from_env


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


def _save_result(result: object) -> Path | None:
    try:
        output_dir = _resolve_output_dir()
    except OSError:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_text = str(result)
    scenario = os.getenv("SCENARIO", "smoke")
    task_text = os.getenv("TASK_TEXT") or os.getenv("TOPIC")

    text_path = output_dir / f"{timestamp}_{scenario}.txt"
    latest_text_path = output_dir / "latest.txt"
    json_path = output_dir / f"{timestamp}_{scenario}.json"
    latest_json_path = output_dir / "latest.json"

    text_path.write_text(result_text, encoding="utf-8")
    latest_text_path.write_text(result_text, encoding="utf-8")

    payload = {
        "timestamp": timestamp,
        "scenario": scenario,
        "task_text": task_text,
        "result": result_text,
    }
    serialized = json.dumps(payload, ensure_ascii=True, indent=2)
    json_path.write_text(serialized, encoding="utf-8")
    latest_json_path.write_text(serialized, encoding="utf-8")
    return text_path


result = run_from_env()
saved_path = _save_result(result)

print("\n=== FINAL RESULT ===\n")
print(result)
if saved_path is not None:
    print(f"\n=== SAVED TO ===\n{saved_path}")
