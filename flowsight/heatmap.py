# =============================================================================
# heatmap.py — FlowSight Customer Heat Map Generator
# สร้าง heat map จาก trajectory data ของลูกค้า
# =============================================================================
import cv2, numpy as np, logging, json
from pathlib import Path

log = logging.getLogger("flowsight.heatmap")

class HeatMapEngine:
    """Accumulate person positions and generate heat map overlay"""

    def __init__(self, width: int = 1280, height: int = 720,
                 decay: float = 0.995):
        self.w       = width
        self.h       = height
        self.decay   = decay   # heat fades over time (1.0 = no decay)
        self._heat   = np.zeros((height, width), dtype=np.float32)
        self._frame_count = 0

    def update(self, persons: list):
        """Add current person positions to heat map"""
        self._frame_count += 1
        # Apply decay every 30 frames
        if self._frame_count % 30 == 0:
            self._heat *= self.decay

        for p in persons:
            cx, cy = p.get("center", (0, 0))
            cx = max(0, min(self.w-1, int(cx)))
            cy = max(0, min(self.h-1, int(cy)))
            # Add gaussian blob around person center
            r = max(self.w, self.h) // 20
            x1 = max(0, cx-r); x2 = min(self.w, cx+r)
            y1 = max(0, cy-r); y2 = min(self.h, cy+r)
            if x2 > x1 and y2 > y1:
                blob = np.zeros((y2-y1, x2-x1), dtype=np.float32)
                bcx, bcy = cx-x1, cy-y1
                for bx in range(blob.shape[1]):
                    for by in range(blob.shape[0]):
                        d = ((bx-bcx)**2 + (by-bcy)**2) ** 0.5
                        blob[by, bx] = max(0, 1.0 - d/r)
                self._heat[y1:y2, x1:x2] += blob

    def get_overlay(self, frame: np.ndarray, alpha: float = 0.45) -> np.ndarray:
        """Return frame with heat map overlay"""
        if self._heat.max() < 0.1:
            return frame

        # Normalize and colorize
        norm = cv2.normalize(self._heat, None, 0, 255, cv2.NORM_MINMAX)
        heat_u8  = norm.astype(np.uint8)
        colored  = cv2.applyColorMap(heat_u8, cv2.COLORMAP_JET)

        # Resize to match frame if needed
        h_f, w_f = frame.shape[:2]
        if colored.shape[:2] != (h_f, w_f):
            colored = cv2.resize(colored, (w_f, h_f))

        # Blend — only where heat > threshold
        mask = (heat_u8 > 15).astype(np.float32)
        if heat_u8.shape != (h_f, w_f):
            mask = cv2.resize(mask, (w_f, h_f))
        mask = mask[:, :, np.newaxis]

        blended = (frame * (1 - alpha * mask) +
                   colored * alpha * mask).astype(np.uint8)
        return blended

    def get_jpeg(self, frame: np.ndarray, alpha: float = 0.45,
                 quality: int = 75) -> bytes:
        """Return heat map overlay as JPEG bytes"""
        overlay = self.get_overlay(frame, alpha)
        _, jpg = cv2.imencode(".jpg", overlay,
                              [cv2.IMWRITE_JPEG_QUALITY, quality])
        return jpg.tobytes()

    def save_snapshot(self, frame: np.ndarray, out_path: str,
                      alpha: float = 0.55):
        """Save heat map snapshot to file"""
        overlay = self.get_overlay(frame, alpha)
        cv2.imwrite(out_path, overlay)
        log.info("Heat map saved: %s", out_path)

    def reset(self):
        self._heat.fill(0)
        self._frame_count = 0
        log.info("Heat map reset")

    def get_top_zones(self, zones_poly: dict, top_n: int = 5) -> list:
        """
        คำนวณว่า zone ไหนมี heat สูงสุด
        คืน list of (zone_id, heat_score) เรียงจากมากไปน้อย
        """
        scores = []
        for zone_id, poly in zones_poly.items():
            if poly is None or len(poly) < 3:
                continue
            mask = np.zeros(self._heat.shape, dtype=np.uint8)
            cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
            zone_heat = self._heat[mask > 0]
            if zone_heat.size > 0:
                scores.append((zone_id, float(zone_heat.mean())))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_n]
