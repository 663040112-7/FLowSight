# =============================================================================
# behavior_engine.py — FlowSight Generic Retail Behavior Engine  v1.2
#
# Changes from v1.1:
#   - PersonState: added _zone_candidate / _zone_candidate_ct for hysteresis
#   - infer(): accepts frame_w/frame_h; passes them to ZoneManager for scaling
#   - infer(): 4-frame hysteresis before committing zone change (kills bbox jitter)
#   - _velocity(): smoothed over a 6-frame window instead of last-2-point delta
#   - velocity threshold normalized to frame diagonal (resolution-independent)
#   - _match_behavior(): takes is_still bool instead of raw velocity px value
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
    return [dict(b) for b in DEFAULT_BEHAVIORS]


def save_behaviors(behaviors: list[dict]):
    with open(BEHAVIORS_CONFIG, "w", encoding="utf-8") as f:
        json.dump(behaviors, f, indent=2, ensure_ascii=False)


@dataclass
class PersonState:
    person_id:          int
    cam_key:            str   = "cam_0"
    zone:               str   = "floor"
    zone_cat:           str   = "floor"
    dwell_start:        float = field(default_factory=time.monotonic)
    behavior_id:        str   = "moving"
    behavior_name:      str   = "Moving"
    needs_staff:        bool  = False
    last_center:        tuple = (0, 0)
    alert_sent:         bool  = False
    is_staff:           bool  = False
    color:              str   = "#888888"
    # Hysteresis: zone doesn't commit until seen N consecutive frames
    _zone_candidate:    str   = field(default="",  repr=False)
    _zone_candidate_ct: int   = field(default=0,   repr=False)

    @property
    def label(self) -> str:
        """Compatibility shim — code elsewhere uses s.label."""
        return "staff" if self.is_staff else "customer"


# Number of consecutive frames a zone must be seen before it commits.
# At ~15 fps this is ~0.27 s — enough to filter YOLO bbox jitter (±15 px)
# without introducing noticeable lag on genuine zone transitions.
ZONE_CONFIRM_FRAMES = 4

# Velocity threshold expressed as a fraction of the frame diagonal per frame.
# 0.004 ≈ 0.4 % of diagonal — at 1920×1080 this is ~9 px/frame, which is
# above typical standing-still jitter (~5–7 px) but below a slow walk (~20 px).
VELOCITY_STILL_NORMALIZED = 0.004


class BehaviorInferenceEngine:
    VELOCITY_STILL_PX   = 3.0    # kept for fallback when frame size is unknown
    STAFF_PROXIMITY_PX  = 150

    def __init__(self, zones_config: str = "zones_config.json",
                 behaviors_config: str = BEHAVIORS_CONFIG):
        self.zone_manager = ZoneManager(zones_config)
        self.states: dict[str, PersonState] = {}
        self._behaviors: list[dict] = load_behaviors()
        self._beh_map:   dict[str, dict] = {b["id"]: b for b in self._behaviors}

    def reload_behaviors(self):
        """Reload from disk — called each detection cycle so UI changes apply live."""
        self._behaviors = load_behaviors()
        self._beh_map   = {b["id"]: b for b in self._behaviors}

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _velocity(traj: list) -> float:
        """
        Smoothed velocity: average displacement over the last 6 trajectory
        points rather than a single-frame delta.  Dramatically reduces
        jitter-induced still/moving flips.
        """
        if len(traj) < 2:
            return 0.0
        window = traj[-min(6, len(traj)):]
        if len(window) < 2:
            return 0.0
        dx = window[-1][0] - window[0][0]
        dy = window[-1][1] - window[0][1]
        return math.hypot(dx, dy) / (len(window) - 1)

    def _is_still(self, traj: list,
                  frame_w: int | None, frame_h: int | None) -> bool:
        """
        Resolution-independent still/moving decision.
        Uses normalised velocity when frame dimensions are known, falls back
        to the legacy pixel threshold otherwise.
        """
        v = self._velocity(traj)
        if frame_w and frame_h:
            diag = math.hypot(frame_w, frame_h)
            return (v / diag) < VELOCITY_STILL_NORMALIZED
        return v <= self.VELOCITY_STILL_PX

    def _match_behavior(self, zone_cat: str, dwell_sec: float,
                        is_still: bool, is_staff: bool) -> dict:
        """
        Priority: staff > highest matching dwell threshold > zone-specific >
                  generic 'any' fallback.

        Sort key: (threshold, zone_specificity)
          zone_specificity=1 when the behavior's zone matches zone_cat exactly
          zone_specificity=0 for 'any' wildcard behaviors

        This ensures a product-zone 'presence' behavior (thresh=0, specific=1)
        beats a generic 'browsing/moving' behavior (thresh=0, specific=0),
        so people standing in the wine zone show as "In wine zone" immediately
        rather than "Moving".
        """
        if is_staff:
            return self._beh_map.get("staff", {
                "id": "staff", "name": "Staff",
                "alert": False, "color": "#f59e0b"})

        candidates: list[tuple[float, int, dict]] = []
        for beh in self._behaviors:
            cat    = beh.get("zone", "any")
            action = beh.get("action", "dwell")
            thresh = float(beh.get("threshold", 0))

            zone_match = (cat == "any" or cat == zone_cat or
                          (cat == "floor" and zone_cat == "floor"))
            if not zone_match:
                continue

            # 1 = zone-specific match, 0 = wildcard 'any' match
            specificity = 0 if cat == "any" else 1

            if action == "dwell" and dwell_sec >= thresh:
                candidates.append((thresh, specificity, beh))
            elif action == "still" and is_still:
                candidates.append((0.0, specificity, beh))
            elif action == "moving" and not is_still:
                candidates.append((0.0, specificity, beh))
            elif action == "presence":
                candidates.append((0.0, specificity, beh))

        if not candidates:
            return self._beh_map.get("moving", {
                "id": "moving", "name": "Moving",
                "alert": False, "color": "#aaaaaa"})

        # Sort by (threshold DESC, specificity DESC) — specific zone wins ties
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][2]

    # ── Public API ────────────────────────────────────────────────────────────

    def infer(self, person: dict, cam_key: str = "cam_0",
              frame_w: int | None = None,
              frame_h: int | None = None) -> PersonState:
        """
        Derive behavior state for one person dict.

        frame_w / frame_h — native resolution of the source frame.
        When provided, zone polygon coordinates are scaled from the zone-authoring
        resolution (stored in zones_config.json _meta) into native pixel space
        before the point-in-polygon test, fixing systematic mis-assignment on
        cameras that don't stream at exactly the authoring resolution.
        """
        state_key = person["state_key"]
        cx, cy    = person["center"]
        traj      = person["trajectory"]

        if state_key not in self.states:
            self.states[state_key] = PersonState(
                person_id=person["id"], cam_key=cam_key)

        st = self.states[state_key]

        current_zone, zone_cat = self.zone_manager.get_zone_and_cat(
            cx, cy, cam_key, frame_w=frame_w, frame_h=frame_h
        )

        still    = self._is_still(traj, frame_w, frame_h)
        now_mono = time.monotonic()
        dwell_sec = now_mono - st.dwell_start

        # ── Zone hysteresis ───────────────────────────────────────────────────
        # Require ZONE_CONFIRM_FRAMES consecutive frames in the new zone before
        # committing the transition.  This eliminates dwell-clock resets caused
        # by YOLO bbox jitter at zone boundaries.
        if current_zone != st.zone:
            if current_zone == st._zone_candidate:
                st._zone_candidate_ct += 1
            else:
                st._zone_candidate    = current_zone
                st._zone_candidate_ct = 1

            if st._zone_candidate_ct >= ZONE_CONFIRM_FRAMES:
                st.zone               = current_zone
                st.zone_cat           = zone_cat
                st.dwell_start        = now_mono
                st.alert_sent         = False
                st._zone_candidate    = ""
                st._zone_candidate_ct = 0
                dwell_sec             = 0.0
            # While accumulating candidate frames, keep the previous zone's
            # dwell clock running — do not reset it yet.
        else:
            # Person is firmly in their confirmed zone; reset candidate.
            st._zone_candidate    = ""
            st._zone_candidate_ct = 0

        st.last_center = (cx, cy)
        st.is_staff    = (zone_cat == "staff")

        beh = self._match_behavior(zone_cat, dwell_sec, still, st.is_staff)
        st.behavior_id   = beh.get("id",    "moving")
        st.behavior_name = beh.get("name",  "Moving")
        st.needs_staff   = bool(beh.get("alert", False))
        st.color         = beh.get("color", "#888888")
        return st

    def remove(self, state_key: str):
        self.states.pop(state_key, None)

    def cleanup_stale(self, active_keys: set[str]):
        stale = [k for k in self.states if k not in active_keys]
        for k in stale:
            del self.states[k]
