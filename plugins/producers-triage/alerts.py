import os
import sys
import json
from pathlib import Path
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PRODUCERS_DIR = Path("/home/ameobius/projects/security-workstation/.hermes/profiles/producers")
LAST_ALERT_FILE = PRODUCERS_DIR / "last_human_ratio_alert.json"

async def _send_alert_once_per_day(event, gateway, guard_status):
    # Check when the last alert was sent
    now_timestamp = datetime.now(timezone.utc).timestamp()
    last_sent = 0.0
    if LAST_ALERT_FILE.is_file():
        try:
            state = json.loads(LAST_ALERT_FILE.read_text())
            last_sent = float(state.get("last_sent_at", 0.0))
        except Exception:
            pass

    # 86400 seconds = 24 hours
    if now_timestamp - last_sent < 86400:
        return

    # Send warning to CHANNELS["help"]
    from . import CHANNELS, _send_reply, run_sanitizer

    ratio = guard_status.get("human_ratio", 0.0)
    min_ratio = guard_status.get("min_human_ratio", 0.55)
    
    alert_text = (
        "внимание: автопостинг временно приостановлен из-за падения активности людей-\n"
        f"текущий human ratio: {ratio:.2f} при норме в {min_ratio:.2f}-\n"
        "для разблокировки требуется больше живого общения или выполнение ручных вопросов через `кработ вопросы`-"
    )
    
    await _send_reply(event, gateway, run_sanitizer(alert_text))
    
    # Save alert timestamp
    try:
        PRODUCERS_DIR.mkdir(parents=True, exist_ok=True)
        LAST_ALERT_FILE.write_text(json.dumps({"last_sent_at": now_timestamp}))
    except Exception as e:
        logger.error(f"Failed to save last alert timestamp: {e}")
