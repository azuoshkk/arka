from pathlib import Path
from datetime import datetime, timezone
import json
import threading

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "logs" / "arka-diagnostic.jsonl"

_lock = threading.Lock()


def log_event(**data):
    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    LOG.parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
