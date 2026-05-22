# alert.py — FlowSight alert manager  v1.1
import time, logging
from behavior_engine import PersonState

log = logging.getLogger("flowsight.alert")

ALERT_COOLDOWN_SEC = 20
_last_alert: dict[str, float] = {}


def check_alert(state: PersonState, cam_key: str = "cam_0") -> bool:
    """Return True if a new alert was fired."""
    if not state.needs_staff or state.is_staff:
        return False
    key = f"{cam_key}_{state.person_id}"
    now = time.monotonic()
    if now - _last_alert.get(key, 0.0) < ALERT_COOLDOWN_SEC:
        return False
    _last_alert[key] = now
    state.alert_sent = True
    log.info("ALERT [%s] Person #%d | Zone: %s | Behavior: %s",
             cam_key, state.person_id, state.zone, state.behavior_name)
    return True


def clear_stale_alerts(max_age_sec: float = 600.0):
    """Remove old alert cooldown entries (call periodically)."""
    cutoff = time.monotonic() - max_age_sec
    stale  = [k for k, t in _last_alert.items() if t < cutoff]
    for k in stale:
        del _last_alert[k]
