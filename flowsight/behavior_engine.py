# =============================================================================
# behavior_engine.py — FlowSight Generic Retail Behavior Engine  v1.1
# =============================================================================
import math, time, json, logging
from dataclasses import dataclass, field
from pathlib import Path
from zones import ZoneManager

log = logging.getLogger("flowsight.engine")

BEHAVIORS_CONFIG = "behaviors_config.json"

DEFAULT_BEHAVIORS: list[dict] = [
    {"id":"browsing",       "name":"Browsing",        "zone":"any",      "action":"moving",   "threshold":0,   "alert":False, "color":"#888888"},
    {"id":"interested",     "name":"Interested",      "zone":"product",  "action":"dwell",    "threshold":25,  "alert":True,  "color":"#f59e0b"},
    {"id":"loitering",      "name":"Loitering",       "zone":"product",  "action":"dwell",    "threshold":90,  "alert":True,  "color":"#ef4444"},
    {"id":"checkout_ready", "name":"Checkout Ready",  "zone":"checkout", "action":"dwell",    "threshold":5,   "alert":True,  "color":"#22c55e"},
    {"id":"waiting",        "name":"Waiting Too Long","zone":"seating",  "action":"dwell",    "threshold":180, "alert":True,  "color":"#ef4444"},
    {"id":"staff",          "name":"Staff",           "zone":"staff",    "action":"presence", "threshold":0,   "alert":False, "color":"#f59e0b"},
    {"id":"idle",           "name":"Idle",            "zone":"floor",    "action":"still",    "threshold":0,   "alert":False, "color":"#555555"},
    {"id":"moving",         "name":"Moving",          "zone":"floor",    "action":"moving",   "threshold":0,   "alert":False, "color":"#aaaaaa"},
]


def load_behaviors() -> list[dict]:
    if Path(BEHAVIORS_CONFIG).exists():
        try:
            with open(BEHAVIORS_CONFIG, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            log.warning("Could not load behaviors config: %s", e)
    return [dict(b) for b in DEFAULT_BEHAVIORS]  # always return a copy


def save_behaviors(behaviors: list[dict]):
    with open(BEHAVIORS_CONFIG, "w", encoding="utf-8") as f:
        json.dump(behaviors, f, indent=2, ensure_ascii=False)


@dataclass
class PersonState:
    person_id:     int
    cam_key:       str   = "cam_0"
    zone:          str   = "floor"
    zone_cat:      str   = "floor"
    dwell_start:   float = field(default_factory=time.monotonic)
    behavior_id:   str   = "moving"
    behavior_name: str   = "Moving"
    needs_staff:   bool  = False
    last_center:   tuple = (0, 0)
    alert_sent:    bool  = False
    is_staff:      bool  = False
    color:         str   = "#888888"


class BehaviorInferenceEngine:
    VELOCITY_STILL_PX  = 3.0
    STAFF_PROXIMITY_PX = 150

    def __init__(self, zones_config: str = "zones_config.json",
                 behaviors_config: str = BEHAVIORS_CONFIG):
        self.zone_manager = ZoneManager(zones_config)
        self.states: dict[str, PersonState] = {}
        self._behaviors: list[dict] = load_behaviors()
        self._beh_map:   dict[str, dict] = {b["id"]: b for b in self._behaviors}

    def reload_behaviors(self):
        """Reload from disk — called each detection cycle so changes apply live."""
        self._behaviors = load_behaviors()
        self._beh_map   = {b["id"]: b for b in self._behaviors}

    # ── Internal helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _velocity(traj: list) -> float:
        if len(traj) < 2:
            return 0.0
        dx = traj[-1][0] - traj[-2][0]
        dy = traj[-1][1] - traj[-2][1]
        return math.hypot(dx, dy)

    def _match_behavior(self, zone_cat: str, dwell_sec: float,
                        velocity: float, is_staff: bool) -> dict:
        """
        Priority: staff > highest matching dwell threshold > action fallback
        """
        if is_staff:
            return self._beh_map.get("staff", {
                "id": "staff", "name": "Staff",
                "alert": False, "color": "#f59e0b"})

        candidates: list[tuple[float, dict]] = []
        for beh in self._behaviors:
            cat    = beh.get("zone", "any")
            action = beh.get("action", "dwell")
            thresh = float(beh.get("threshold", 0))

            zone_match = (cat == "any" or cat == zone_cat or
                          (cat == "floor" and zone_cat == "floor"))
            if not zone_match:
                continue

            if action == "dwell" and dwell_sec >= thresh:
                candidates.append((thresh, beh))
            elif action == "still" and velocity <= self.VELOCITY_STILL_PX:
                candidates.append((0.0, beh))
            elif action == "moving" and velocity > self.VELOCITY_STILL_PX:
                candidates.append((0.0, beh))
            elif action == "presence":
                candidates.append((0.0, beh))

        if not candidates:
            return self._beh_map.get("moving", {
                "id": "moving", "name": "Moving",
                "alert": False, "color": "#aaaaaa"})

        # highest threshold wins (most specific dwell behavior)
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # ── Public API ────────────────────────────────────────────────────────────
    def infer(self, person: dict, cam_key: str = "cam_0") -> PersonState:
        state_key = person["state_key"]
        cx, cy    = person["center"]
        traj      = person["trajectory"]

        if state_key not in self.states:
            self.states[state_key] = PersonState(
                person_id=person["id"], cam_key=cam_key)

        st = self.states[state_key]
        current_zone, zone_cat = self.zone_manager.get_zone_and_cat(cx, cy, cam_key)
        velocity  = self._velocity(traj)
        now_mono  = time.monotonic()
        dwell_sec = now_mono - st.dwell_start

        if current_zone != st.zone:
            st.zone        = current_zone
            st.zone_cat    = zone_cat
            st.dwell_start = now_mono
            st.alert_sent  = False
            dwell_sec      = 0.0

        st.last_center = (cx, cy)
        st.is_staff    = (zone_cat == "staff")

        beh = self._match_behavior(zone_cat, dwell_sec, velocity, st.is_staff)
        st.behavior_id   = beh.get("id", "moving")
        st.behavior_name = beh.get("name", "Moving")
        st.needs_staff   = bool(beh.get("alert", False))
        st.color         = beh.get("color", "#888888")
        return st

    def remove(self, state_key: str):
        self.states.pop(state_key, None)

    def cleanup_stale(self, active_keys: set[str]):
        stale = [k for k in self.states if k not in active_keys]
        for k in stale:
            del self.states[k]
