# zones.py — FlowSight Zone Manager  v1.1
import cv2, json, logging
import numpy as np
from pathlib import Path

log = logging.getLogger("flowsight.zones")

ZONES_CONFIG = "zones_config.json"

ZONE_CATEGORIES: dict[str, dict] = {
    "product":  {"label": "Product area", "color": "#3b82f6"},
    "checkout": {"label": "Checkout",     "color": "#22c55e"},
    "seating":  {"label": "Seating",      "color": "#f59e0b"},
    "staff":    {"label": "Staff area",   "color": "#a855f7"},
    "entrance": {"label": "Entrance",     "color": "#14b8a6"},
    "custom":   {"label": "Custom",       "color": "#6b7280"},
    "floor":    {"label": "Floor",        "color": "#374151"},
}

CATEGORY_PRIORITY: dict[str, int] = {
    "staff": 10, "checkout": 9, "seating": 6,
    "entrance": 4, "product": 2, "custom": 1, "floor": 0,
}


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (100, 100, 100)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (b, g, r)
    except ValueError:
        return (100, 100, 100)


def get_zone_color(zone_obj: dict) -> tuple[int, int, int]:
    hex_color = zone_obj.get("color") or \
                ZONE_CATEGORIES.get(zone_obj.get("category", "floor"),
                                    {}).get("color", "#6b7280")
    return _hex_to_bgr(hex_color)


def get_priority(category: str) -> int:
    return CATEGORY_PRIORITY.get(category, 0)


class ZoneManager:
    """
    New format (zones_config.json):
      {"cam_0": {"zone_id": {"name":"..","category":"product","color":"#hex","points":[[x,y]..]}}}
    Legacy format (list of points) is auto-migrated on load.
    """
    def __init__(self, config_path: str = ZONES_CONFIG):
        self.cameras:    dict[str, dict[str, np.ndarray]] = {}
        self.zones_meta: dict[str, dict[str, dict]]       = {}
        if Path(config_path).exists():
            try:
                self._load(config_path)
            except Exception as e:
                log.error("Zone config load error: %s", e)

    def _infer_category(self, zone_id: str) -> str:
        z = zone_id.lower()
        if any(w in z for w in ("wine", "product", "shelf")): return "product"
        if any(w in z for w in ("checkout", "counter")):       return "checkout"
        if any(w in z for w in ("seat", "bar")):               return "seating"
        if any(w in z for w in ("seller", "staff")):           return "staff"
        if any(w in z for w in ("entrance", "entry")):         return "entrance"
        return "custom"

    def _load(self, config_path: str):
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f)
        for cam_key, zones in raw.items():
            self.cameras[cam_key]    = {}
            self.zones_meta[cam_key] = {}
            for zone_id, zone_data in zones.items():
                if isinstance(zone_data, list):
                    pts = zone_data
                    cat = self._infer_category(zone_id)
                    meta = {"name":     zone_id.replace("_", " ").title(),
                            "category": cat,
                            "color":    ZONE_CATEGORIES.get(cat, {}).get("color", "#6b7280")}
                elif isinstance(zone_data, dict):
                    pts  = zone_data.get("points", [])
                    meta = {"name":     zone_data.get("name", zone_id),
                            "category": zone_data.get("category", "custom"),
                            "color":    zone_data.get("color", "#6b7280")}
                else:
                    continue
                if pts:
                    self.cameras[cam_key][zone_id]    = np.array(pts, dtype=np.int32)
                    self.zones_meta[cam_key][zone_id] = meta

    def get_zone_and_cat(self, cx: int, cy: int,
                         cam_key: str = "cam_0") -> tuple[str, str]:
        matched: list[tuple[int, str, str]] = []
        pt = (float(cx), float(cy))
        for zid, poly in self.cameras.get(cam_key, {}).items():
            if len(poly) < 3:
                continue
            if cv2.pointPolygonTest(poly, pt, False) >= 0:
                cat = self.zones_meta[cam_key][zid].get("category", "custom")
                matched.append((get_priority(cat), zid, cat))
        if not matched:
            return "floor", "floor"
        matched.sort(reverse=True)
        return matched[0][1], matched[0][2]

    def get_polygons(self, cam_key: str = "cam_0") -> dict[str, np.ndarray]:
        return self.cameras.get(cam_key, {})

    def get_meta(self, cam_key: str = "cam_0") -> dict[str, dict]:
        return self.zones_meta.get(cam_key, {})
