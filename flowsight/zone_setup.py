# =============================================================================
# zone_setup.py — Interactive zone drawing tool for FlowSight
#
# Usage:
#   python zone_setup.py <source> [<source2> ...]
#   source: video file, image file, or camera index (0, 1, …) or rtsp://…
#
#   python zone_setup.py cam0.mp4 cam1.mp4
#   python zone_setup.py 0                     ← webcam
#   python zone_setup.py snapshot.jpg
#
# Controls (in the drawing window):
#   Left-click  — add a polygon point
#   Right-click — finish current zone polygon (need ≥ 3 points)
#   Z           — undo last point
#   C           — cancel current zone (discard points)
#   Q / ESC     — finish this camera and move to the next
#
# Zone categories (prompted via terminal after each polygon):
#   product, checkout, seating, staff, entrance, custom
#
# Output: zones_config.json (creates or updates existing file)
#         _meta is always written to record the authoring resolution so
#         ZoneManager can scale polygons to any camera streaming resolution.
# =============================================================================
import sys, os, json, time
import cv2
import numpy as np
from pathlib import Path
from zones import ZoneManager, ZONE_CATEGORIES, get_zone_color

# All zones are authored at this resolution.  The frame is resized to this
# before drawing so coordinate math is predictable.
AUTHOR_W, AUTHOR_H = 960, 540

# Colours used while drawing (BGR)
POINT_COLOR  = (0, 255, 255)
LINE_COLOR   = (0, 200, 255)
FILL_COLOR   = (0, 180, 255)
DONE_COLORS  = {
    "product":  (255, 100, 60),
    "checkout": (80,  200, 80),
    "seating":  (60,  180, 255),
    "staff":    (200, 80,  220),
    "entrance": (80,  220, 200),
    "custom":   (160, 160, 160),
}


# ── Frame helpers ─────────────────────────────────────────────────────────────

def grab_frame(source) -> tuple[bool, np.ndarray | None]:
    """Return (ok, frame) at AUTHOR_W × AUTHOR_H."""
    # Image file
    if isinstance(source, str):
        ext = os.path.splitext(source)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            frame = cv2.imread(source)
            if frame is None:
                print(f"  Cannot read image: {source}")
                return False, None
            return True, cv2.resize(frame, (AUTHOR_W, AUTHOR_H))

    # Video / live camera — show a frame-picker slider for files
    cap   = cv2.VideoCapture(source)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total <= 0:
        # Live stream — grab first available frame
        for _ in range(30):
            ret, frame = cap.read()
            if ret:
                cap.release()
                return True, cv2.resize(frame, (AUTHOR_W, AUTHOR_H))
            time.sleep(0.1)
        cap.release()
        print(f"  No frame received from: {source}")
        return False, None

    # File — interactive slider so the user can pick a representative frame
    win = "Pick a frame — ENTER / SPACE = select,  Q = cancel"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, AUTHOR_W, AUTHOR_H)
    pos = [total // 3]
    cv2.createTrackbar("Frame", win, pos[0], total - 1,
                       lambda v: pos.__setitem__(0, v))
    selected = [None]

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos[0])
        ret, frame = cap.read()
        if not ret:
            break
        fps  = cap.get(cv2.CAP_PROP_FPS) or 25
        info = (f"Frame {pos[0]}/{total-1}  ({pos[0]/fps:.1f}s)"
                f"  ENTER=select  Q=cancel")
        disp = cv2.resize(frame, (AUTHOR_W, AUTHOR_H))
        cv2.putText(disp, info, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
        cv2.putText(disp, info, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.imshow(win, disp)
        key = cv2.waitKey(30) & 0xFF
        if key in (13, 32):
            selected[0] = cv2.resize(frame, (AUTHOR_W, AUTHOR_H))
            break
        if key in (ord('q'), 27):
            break

    cv2.destroyWindow(win)
    cap.release()
    if selected[0] is not None:
        return True, selected[0]
    return False, None


# ── Zone drawing ──────────────────────────────────────────────────────────────

def draw_zones_on(background: np.ndarray,
                  saved_zones: dict) -> np.ndarray:
    """Overlay already-saved zones onto background for context."""
    overlay = background.copy()
    for zid, zdata in saved_zones.items():
        pts = np.array(zdata["points"], dtype=np.int32)
        if len(pts) < 3:
            continue
        cat   = zdata.get("category", "custom")
        color = DONE_COLORS.get(cat, (160, 160, 160))
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(overlay, [pts], True, color, 2)
        cx = int(pts.mean(0)[0])
        cy = int(pts.mean(0)[1])
        label = zdata.get("name", zid)
        cv2.putText(overlay, label, (cx - 40, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    return cv2.addWeighted(overlay, 0.35, background, 0.65, 0)


def pick_category() -> tuple[str, str]:
    """Ask the user to pick a zone category and enter a name."""
    cats = list(ZONE_CATEGORIES.keys())
    print("\n  Zone categories:")
    for i, c in enumerate(cats):
        print(f"    {i+1}. {c}")
    while True:
        raw = input("  Category number (or name) [1]: ").strip()
        if not raw:
            raw = "1"
        # Numeric
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(cats):
                cat = cats[idx]
                break
        except ValueError:
            pass
        # Name
        if raw.lower() in cats:
            cat = raw.lower()
            break
        print("  Invalid choice — try again.")

    default_name = cat.replace("_", " ").title()
    name_raw = input(f"  Zone name [{default_name}]: ").strip()
    name = name_raw if name_raw else default_name
    return cat, name


def collect_zone(base_frame: np.ndarray,
                 cam_key: str,
                 saved_zones: dict,
                 zone_number: int) -> dict | None:
    """
    Interactive polygon drawing.
    Returns a zone dict {"name":…, "category":…, "color":…, "points":[[x,y]…]}
    or None if the user cancels.
    """
    win   = f"{cam_key} — Zone {zone_number}  |  Lclick=add  Rclick=finish  Z=undo  C=cancel  Q=done"
    points: list[tuple[int, int]] = []
    done  = [False]
    cancel = [False]

    def mouse_cb(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN:
            if len(points) >= 3:
                done[0] = True

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, AUTHOR_W, AUTHOR_H)
    cv2.setMouseCallback(win, mouse_cb)

    while True:
        frame = draw_zones_on(base_frame, saved_zones)

        # Draw current in-progress polygon
        for pt in points:
            cv2.circle(frame, pt, 5, POINT_COLOR, -1)
        if len(points) >= 2:
            cv2.polylines(frame, [np.array(points, dtype=np.int32)],
                          False, LINE_COLOR, 2)
        if len(points) >= 3:
            overlay = frame.copy()
            cv2.fillPoly(overlay, [np.array(points, dtype=np.int32)], FILL_COLOR)
            frame = cv2.addWeighted(overlay, 0.25, frame, 0.75, 0)

        hint = (f"Points: {len(points)}  |  "
                "Lclick=add  Rclick=finish(≥3)  Z=undo  C=cancel  Q=next-cam")
        cv2.putText(frame, hint, (8, AUTHOR_H - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
        cv2.putText(frame, hint, (8, AUTHOR_H - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        cv2.imshow(win, frame)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('z') and points:
            points.pop()
        elif key == ord('c'):
            cancel[0] = True
            break
        elif key in (ord('q'), 27):
            # Signal caller to stop adding zones for this camera
            cv2.destroyWindow(win)
            return "DONE"

        if done[0]:
            break

    cv2.destroyWindow(win)

    if cancel[0] or len(points) < 3:
        print("  Zone cancelled.")
        return None

    # Prompt for category and name in terminal
    cat, name = pick_category()
    color = ZONE_CATEGORIES.get(cat, {}).get("color", "#6b7280")
    return {
        "name":     name,
        "category": cat,
        "color":    color,
        "points":   [list(pt) for pt in points],
    }


# ── Config save/load ──────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    if Path(path).exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  Warning: could not read existing config: {e}")
    return {}


def save_config(path: str, config: dict):
    # Always write/update _meta so ZoneManager knows authoring resolution
    config["_meta"] = {"w": AUTHOR_W, "h": AUTHOR_H}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved → {path}")
    print(f"  Authoring resolution stored: {AUTHOR_W}×{AUTHOR_H}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    sources = sys.argv[1:]
    if not sources:
        print("Usage: python zone_setup.py <video|image|0|rtsp://…> [source2 …]")
        print("Example: python zone_setup.py cam0.mp4 cam1.mp4")
        sys.exit(0)

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "zones_config.json")
    config = load_config(config_path)

    for i, src in enumerate(sources):
        cam_key = f"cam_{i}"
        try:
            src = int(src)
        except (ValueError, TypeError):
            pass

        print(f"\n{'='*60}")
        print(f"Camera: {cam_key}  |  Source: {src}")
        print("="*60)

        ret, frame = grab_frame(src)
        if not ret or frame is None:
            print(f"  Skipping — cannot open source: {src}")
            continue

        if cam_key not in config:
            config[cam_key] = {}

        zone_number = len(config[cam_key]) + 1
        print(f"  Existing zones for {cam_key}: {list(config[cam_key].keys()) or 'none'}")
        print("  Draw new zones.  Press Q in the drawing window when done with this camera.")

        while True:
            result = collect_zone(frame, cam_key, config[cam_key], zone_number)

            if result == "DONE":
                print(f"  Done with {cam_key}.")
                break
            if result is None:
                # User cancelled this zone — ask if they want another
                again = input("  Draw another zone for this camera? [Y/n]: ").strip().lower()
                if again == 'n':
                    break
                continue

            # Generate a unique zone ID
            import time as _t
            zone_id = f"z_{int(_t.time() * 1000) % 10_000_000_000:010d}"
            config[cam_key][zone_id] = result
            print(f"  ✓ Zone '{result['name']}' ({result['category']}) saved as {zone_id}")

            again = input("  Draw another zone for this camera? [Y/n]: ").strip().lower()
            if again == 'n':
                break
            zone_number += 1

    save_config(config_path, config)
    print("\nAll done — zones_config.json updated.")


if __name__ == "__main__":
    main()
