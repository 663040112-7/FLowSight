# =============================================================================
# server.py — FlowSight Generic Retail AI  v1.1 (reviewed & fixed)
# =============================================================================
import sys, os, time, json, queue, threading, base64, sqlite3, logging, contextlib
from pathlib import Path

# ── PyInstaller path fix ──────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_DIR)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2, numpy as np
from flask import Flask, Response, jsonify, request

# ── Writable data folder (defined once, used by logging + config) ─────────────
# Use ProgramData whenever running from Program Files (read-only for normal users)
# This covers both PyInstaller builds AND raw .py via embedded Python
_prog_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
_prog_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
_in_program_files = (
    APP_DIR.lower().startswith(_prog_files.lower()) or
    APP_DIR.lower().startswith(_prog_files_x86.lower())
)

if getattr(sys, "frozen", False) or _in_program_files:
    DATA_DIR = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "FlowSight")
else:
    DATA_DIR = APP_DIR

os.makedirs(DATA_DIR, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
log_handlers = [logging.StreamHandler()]
if getattr(sys, "frozen", False):
    log_file = os.path.join(DATA_DIR, "flowsight.log")
    log_handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
else:
    # Fix Windows terminal encoding
    import sys as _sys
    if hasattr(_sys.stdout, 'reconfigure'):
        try: _sys.stdout.reconfigure(encoding='utf-8')
        except Exception: pass

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=log_handlers)
log = logging.getLogger("flowsight")

# ── Config ────────────────────────────────────────────────────────────────────

CLOUD_MODE   = os.environ.get("CLOUD_MODE", "0") == "1"
DB_PATH      = os.path.join(DATA_DIR, "behavior_log.db")

# Writable configs live in DATA_DIR (ProgramData when installed to Program Files).
# Shipped defaults sit in APP_DIR and are seeded into DATA_DIR on first run so a
# standard (non-admin) user can save zone, behavior, and brand changes.
import shutil as _shutil
if DATA_DIR != APP_DIR:
    for _cfg in ("zones_config.json", "behaviors_config.json", "brand_config.json"):
        _dst = os.path.join(DATA_DIR, _cfg)
        _src = os.path.join(APP_DIR, _cfg)
        if not os.path.exists(_dst) and os.path.exists(_src):
            try:
                _shutil.copy2(_src, _dst)
                log.info("Seeded %s into %s", _cfg, DATA_DIR)
            except Exception as _e:
                log.warning("Could not seed %s: %s", _cfg, _e)

ZONES_CONFIG = os.path.join(DATA_DIR, "zones_config.json")
BEHS_CONFIG  = os.path.join(DATA_DIR, "behaviors_config.json")
BRAND_CONFIG = os.path.join(DATA_DIR, "brand_config.json")
MODEL_PATH   = os.path.join(APP_DIR, "yolov8n.pt")

# Point the behavior engine's module-level config path at the writable copy so
# load_behaviors()/save_behaviors() (which read the module global) use DATA_DIR.
try:
    import behavior_engine as _be
    _be.BEHAVIORS_CONFIG = BEHS_CONFIG
except Exception as _e:
    log.warning("Could not set behavior_engine config path: %s", _e)
# Look for index.html in templates/ first, then root (supports both layouts)
_tmpl_in_templates = os.path.join(APP_DIR, "templates", "index.html")
_tmpl_in_root      = os.path.join(APP_DIR, "index.html")
TMPL_PATH = _tmpl_in_templates if os.path.exists(_tmpl_in_templates) else _tmpl_in_root
TZ           = int(os.environ.get("TZ_OFFSET", "7"))
MAX_ALERTS   = 200

# ── Brand ─────────────────────────────────────────────────────────────────────
def load_brand() -> dict:
    try:
        with open(BRAND_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"name": "FlowSight", "tagline": "Retail Intelligence Platform",
                "color": "#6366f1"}

# ── Shared state (thread-safe reads, writes inside lock where needed) ─────────
_state_lock = threading.Lock()
state = {
    "running": False,
    "rtsp_url": "",
    "conf": 0.40,
    "anonymize": True,
    "dwell_interested": 25,
    "dwell_loitering": 90,
    "dwell_checkout_min": 5,
    "dwell_seating_waiting": 180,
    "gemini_api_key": "",
    "claude_api_key": "",
    # Multi-camera: list of camera configs
    "cameras": [
        {"id": "cam_0", "name": "Camera 1", "rtsp_url": "", "enabled": True}
    ],
}

frame_q    = queue.Queue(maxsize=3)
heat_frame: list = [None]
stop_evt   = threading.Event()
eng_thread = None  # kept for backward compat

# ── Multi-camera state ────────────────────────────────────────────────────────
_cam_frames:  dict = {}   # cam_id -> latest frame (numpy array)
_cam_threads: dict = {}   # cam_id -> threading.Thread
_cam_stops:   dict = {}   # cam_id -> threading.Event
_cam_status:  dict = {}   # cam_id -> {"running": bool, "msg": str}
_cam_huds:    dict = {}   # cam_id -> {"cust":int,"seller":int,"alert":int}
_cams_lock    = threading.Lock()

# CPU-only mode — GPU/CUDA intentionally disabled for stability across PCs
_DEVICE:   str   = "cpu"
_GPU_NAME: str   = ""
_GPU_VRAM: float = 0.0

def _detect_device() -> str:
    return "cpu"

# Each camera thread creates its own YOLO model instance (see camera_engine_loop).
# Sharing a single model with persist=True across threads corrupts ByteTrack
# internal state — this caused crashes on CPU where no inference lock existed.

hud_lock = threading.Lock()
hud      = {"running": False, "cust": 0, "seller": 0, "alert": 0}

alerts_lock = threading.Lock()
alerts      = []

app = Flask(__name__)

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def ensure_db():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     REAL    NOT NULL,
        cam_key       TEXT    NOT NULL DEFAULT 'cam_0',
        person_id     INTEGER NOT NULL,
        zone          TEXT    NOT NULL DEFAULT 'floor',
        zone_name     TEXT    NOT NULL DEFAULT '',
        behavior_id   TEXT    NOT NULL DEFAULT '',
        behavior_name TEXT    NOT NULL DEFAULT '',
        needs_staff   INTEGER NOT NULL DEFAULT 0,
        is_new_visit  INTEGER NOT NULL DEFAULT 1)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(timestamp)")
    migrations = [
        "ALTER TABLE events ADD COLUMN zone_name TEXT DEFAULT ''",
        "ALTER TABLE events ADD COLUMN behavior_id TEXT DEFAULT ''",
        "ALTER TABLE events ADD COLUMN behavior_name TEXT DEFAULT ''",
        "ALTER TABLE events ADD COLUMN is_new_visit INTEGER DEFAULT 1",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    try:
        conn.execute("""UPDATE events
            SET behavior_id=behavior, behavior_name=behavior
            WHERE behavior_id='' AND behavior IS NOT NULL""")
    except Exception:
        pass
    conn.commit()
    conn.close()

ensure_db()

# Load saved cameras from brand_config on startup
try:
    _saved = load_brand().get("cameras")
    if _saved and isinstance(_saved, list) and len(_saved) > 0:
        with _state_lock:
            state["cameras"] = _saved
            state["rtsp_url"] = _saved[0].get("rtsp_url", "")
        log.info("Loaded %d camera(s) from config", len(_saved))
except Exception as _e:
    log.warning("Could not load cameras from config: %s", _e)

def _today_str() -> str:
    import datetime
    return (datetime.datetime.utcnow() +
            datetime.timedelta(hours=TZ)).strftime("%Y-%m-%d")

def _dc() -> str:
    return f"date(datetime(timestamp,'unixepoch','+{TZ} hours'))"

# ── Stream ────────────────────────────────────────────────────────────────────
_last_frame: list = [None]   # mutable container avoids global keyword

@app.route("/api/jpeg")
def api_jpeg():
    try:
        frame = frame_q.get_nowait()
        _last_frame[0] = frame
    except queue.Empty:
        frame = _last_frame[0]
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return Response(b"", status=500)
    return Response(jpg.tobytes(), mimetype="image/jpeg",
                    headers={"Cache-Control": "no-cache, no-store",
                             "Pragma": "no-cache"})

def _mjpeg_generator(cam_id):
    """Generator that yields MJPEG frames for a given camera"""
    import time as _time
    boundary = b"--frame"
    while True:
        try:
            # Get frame for this camera
            with _cams_lock:
                frame = _cam_frames.get(cam_id)
            if frame is None:
                frame = _last_frame[0]
            if frame is None:
                # Send blank frame
                frame = np.zeros((480, 640, 3), dtype=np.uint8)

            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                jpg_bytes = jpg.tobytes()
                yield (boundary + b"\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpg_bytes)).encode() + b"\r\n"
                       b"\r\n" + jpg_bytes + b"\r\n")
            _time.sleep(0.033)  # ~30 FPS cap
        except GeneratorExit:
            # Client disconnected cleanly (tab switch, page navigation)
            log.debug("[MJPEG:%s] Client disconnected", cam_id)
            return
        except Exception as e:
            log.warning("[MJPEG:%s] Stream error: %s", cam_id, e)
            return

@app.route("/api/stream/<cam_id>")
def api_stream_cam(cam_id):
    """MJPEG stream for a specific camera — smooth real-time video"""
    return Response(
        _mjpeg_generator(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store",
                 "Pragma": "no-cache",
                 "Connection": "close"}
    )

@app.route("/api/stream")
def api_stream():
    """MJPEG stream for default camera (cam_0)"""
    return api_stream_cam("cam_0")

@app.route("/api/frame")
def api_frame():
    """Legacy single-camera frame — returns cam_0"""
    return api_frame_cam("cam_0")

@app.route("/api/frame/<cam_id>")
def api_frame_cam(cam_id):
    with _cams_lock:
        frame = _cam_frames.get(cam_id)
    if frame is None:
        frame = _last_frame[0]
    if frame is None:
        return jsonify({"ok": False, "msg": "no frame yet"})
    h, w = frame.shape[:2]
    if w > 1280:
        scale = 1280 / w
        frame = cv2.resize(frame, (1280, int(h * scale)))
        h, w = frame.shape[:2]
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return jsonify({"ok": False, "msg": "encode failed"})
    return jsonify({"ok": True,
                    "image": base64.b64encode(jpg.tobytes()).decode(),
                    "width": w, "height": h})

# ── Camera CRUD ───────────────────────────────────────────────────────────────
@app.route("/api/cameras")
def api_cameras_get():
    with _state_lock:
        cams = state.get("cameras", [{"id":"cam_0","name":"Camera 1","rtsp_url":"","enabled":True}])
    with _cams_lock:
        statuses = dict(_cam_status)
    result = []
    for c in cams:
        cid = c["id"]
        result.append({**c,
            "running": statuses.get(cid, {}).get("running", False),
            "msg":     statuses.get(cid, {}).get("msg", "")})
    return jsonify({"ok": True, "cameras": result})

@app.route("/api/cameras/save", methods=["POST"])
def api_cameras_save():
    data = request.get_json() or {}
    cams = data.get("cameras", [])
    ids = set()
    for c in cams:
        if not c.get("id"):
            return jsonify({"ok": False, "msg": "Camera ID required"})
        if c["id"] in ids:
            return jsonify({"ok": False, "msg": f"Duplicate camera ID: {c['id']}"})
        ids.add(c["id"])
    with _state_lock:
        state["cameras"] = cams
        if cams:
            state["rtsp_url"] = cams[0].get("rtsp_url", "")
    save_settings_to_disk()
    return jsonify({"ok": True})

# ── Per-camera start/stop ─────────────────────────────────────────────────────
@app.route("/api/start", methods=["POST"])
def api_start():
    """Start all enabled cameras"""
    if CLOUD_MODE:
        return jsonify({"ok": False, "msg": "Cloud mode"})
    with _state_lock:
        cams = state.get("cameras", [])
        if not cams:
            rtsp = state.get("rtsp_url", "").strip()
            if rtsp:
                cams = [{"id":"cam_0","name":"Camera 1","rtsp_url":rtsp,"enabled":True}]
    started = []
    for cam in cams:
        if not cam.get("enabled", True): continue
        cid = cam["id"]
        with _cams_lock:
            t = _cam_threads.get(cid)
            if t and t.is_alive(): continue
            evt = threading.Event()
            _cam_stops[cid]  = evt
            _cam_status[cid] = {"running": False, "msg": "Starting..."}
        t = threading.Thread(target=camera_engine_loop,
                             args=(cam, evt), daemon=True, name=f"cam_{cid}")
        with _cams_lock:
            _cam_threads[cid] = t
        t.start()
        started.append(cid)
    with _state_lock:
        state["running"] = True
    stop_evt.clear()
    return jsonify({"ok": True, "started": started})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_evt.set()
    with _cams_lock:
        for evt in _cam_stops.values():
            evt.set()
    # Wait long enough for grab threads to exit their blocking cap.read().
    # READ_TIMEOUT_MSEC=3 s + grab join=5 s + inference cleanup ≤ 8 s total.
    for t in list(_cam_threads.values()):
        if t.is_alive():
            t.join(timeout=8.0)
        if t.is_alive():
            log.warning("[Stop] Thread %s still alive after 8 s join", t.name)
    with _cams_lock:
        _cam_threads.clear()
        _cam_stops.clear()
        _cam_frames.clear()
        for cid in list(_cam_status.keys()):
            _cam_status[cid] = {"running": False, "msg": "Stopped"}
    # Clear the last frame so the MJPEG stream shows a black frame
    # instead of a frozen snapshot when the camera is stopped.
    _last_frame[0] = None
    stop_evt.clear()   # reset for the next api_start call
    with _state_lock:
        state["running"] = False
    return jsonify({"ok": True})

@app.route("/api/start/<cam_id>", methods=["POST"])
def api_start_cam(cam_id):
    with _state_lock:
        cams = state.get("cameras", [])
    cam = next((c for c in cams if c["id"] == cam_id), None)
    if not cam:
        return jsonify({"ok": False, "msg": f"Camera {cam_id} not found"})
    with _cams_lock:
        t = _cam_threads.get(cam_id)
        if t and t.is_alive():
            return jsonify({"ok": False, "msg": "Already running"})
        evt = threading.Event()
        _cam_stops[cam_id]  = evt
        _cam_status[cam_id] = {"running": False, "msg": "Starting..."}
    t = threading.Thread(target=camera_engine_loop,
                         args=(cam, evt), daemon=True, name=f"cam_{cam_id}")
    with _cams_lock:
        _cam_threads[cam_id] = t
    t.start()
    with _state_lock:
        state["running"] = True
    return jsonify({"ok": True})

@app.route("/api/stop/<cam_id>", methods=["POST"])
def api_stop_cam(cam_id):
    with _cams_lock:
        evt = _cam_stops.get(cam_id)
    if evt:
        evt.set()
    with _cams_lock:
        t = _cam_threads.get(cam_id)
    if t and t.is_alive():
        t.join(timeout=8.0)   # matches grab(5s) + READ_TIMEOUT(3s) budget
    if t and t.is_alive():
        log.warning("[StopCam] Thread %s still alive after 8 s", cam_id)
    with _cams_lock:
        _cam_threads.pop(cam_id, None)
        _cam_stops.pop(cam_id, None)
        _cam_frames.pop(cam_id, None)
        _cam_status[cam_id] = {"running": False, "msg": "Stopped"}
    # Clear stale frame so MJPEG shows black not a frozen snapshot
    _last_frame[0] = None
    with _cams_lock:
        any_running = any(t.is_alive() for t in _cam_threads.values())
    if not any_running:
        with _state_lock:
            state["running"] = False
    return jsonify({"ok": True})

@app.route("/api/hud")
def api_hud():
    from collections import Counter
    with _cams_lock:
        huds = dict(_cam_huds)
    total_cust = sum(h.get("cust", 0) for h in huds.values())
    total_sell = sum(h.get("seller", 0) for h in huds.values())
    total_alrt = sum(h.get("alert", 0) for h in huds.values())
    merged_zones: Counter = Counter()
    for h in huds.values():
        merged_zones.update(h.get("zones", {}))
    with _state_lock:
        running = state.get("running", False)
    return jsonify({
        "running":  running,
        "cust":     total_cust,
        "seller":   total_sell,
        "alert":    total_alrt,
        "zones":    dict(merged_zones),
        "cams":     huds,
        "device":   "cpu",
        "gpu_name": None,
    })

# ── Legacy engine removed — see camera_engine_loop ──────────────────────────────

@app.route("/api/alerts")
def api_alerts():
    with alerts_lock:
        return jsonify(list(alerts[-50:]))

# ── Stats ─────────────────────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    if not Path(DB_PATH).exists():
        return jsonify({"total": 0, "interested": 0, "purchasing": 0, "top_zone": "—"})
    today = _today_str()
    dc    = _dc()
    try:
        conn = get_conn()
        def q(sql, p=()):
            return conn.execute(sql, p).fetchall()
        try:
            total = q(f"SELECT COUNT(*) FROM events WHERE is_new_visit=1 AND {dc}=?", (today,))[0][0]
        except Exception:
            total = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE {dc}=?", (today,))[0][0]
        if total == 0:
            total = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE {dc}=?", (today,))[0][0]
        inter = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior_id='interested' AND {dc}=?", (today,))[0][0]
        purch = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior_id='checkout_ready' AND {dc}=?", (today,))[0][0]
        top_z = q(f"SELECT zone_name, COUNT(*) n FROM events WHERE zone!='floor' AND {dc}=? GROUP BY zone_name ORDER BY n DESC LIMIT 1", (today,))
        conn.close()
        return jsonify({"total": total, "interested": inter, "purchasing": purch,
                        "top_zone": top_z[0][0] if top_z else "—"})
    except Exception as e:
        log.error("api_stats error: %s", e)
        return jsonify({"total": 0, "interested": 0, "purchasing": 0, "top_zone": "—"})

@app.route("/api/hourly")
def api_hourly():
    if not Path(DB_PATH).exists():
        return jsonify({"labels": [], "datasets": []})
    today = _today_str()
    dc    = _dc()
    hf    = f"strftime('%H',datetime(timestamp,'unixepoch','+{TZ} hours'))"
    COLOR_MAP = ["#6366f1","#f59e0b","#22c55e","#ef4444",
                 "#a855f7","#14b8a6","#f97316","#3b82f6"]
    try:
        conn = get_conn()
        rows = conn.execute(
            f"SELECT {hf} hr, behavior_name, COUNT(*) n FROM events "
            f"WHERE {dc}=? GROUP BY hr, behavior_name ORDER BY hr",
            (today,)).fetchall()
        conn.close()
        labels  = [f"{h:02d}:00" for h in range(24)]
        beh_set = list(dict.fromkeys(r[1] for r in rows if r[1]))
        datasets = []
        for i, beh in enumerate(beh_set[:8]):
            data = [0] * 24
            for hr, b, n in rows:
                if b == beh and hr:
                    data[int(hr)] = n
            col = COLOR_MAP[i % len(COLOR_MAP)]
            datasets.append({"label": beh, "data": data,
                              "backgroundColor": col + "99",
                              "borderColor": col, "borderWidth": 1})
        return jsonify({"labels": labels, "datasets": datasets})
    except Exception as e:
        log.error("api_hourly error: %s", e)
        return jsonify({"labels": [], "datasets": []})

@app.route("/api/zones_activity")
def api_zones_activity():
    if not Path(DB_PATH).exists():
        return jsonify([])
    today = _today_str()
    dc    = _dc()
    try:
        conn = get_conn()
        rows = conn.execute(
            f"SELECT zone_name, COUNT(*) n FROM events "
            f"WHERE zone!='floor' AND {dc}=? "
            f"GROUP BY zone_name ORDER BY n DESC LIMIT 10",
            (today,)).fetchall()
        conn.close()
        return jsonify([{"zone": r[0] or "unknown", "count": r[1]} for r in rows])
    except Exception as e:
        log.error("api_zones_activity error: %s", e)
        return jsonify([])

# ── Zones CRUD ────────────────────────────────────────────────────────────────
@app.route("/api/zones/load")
def api_zones_load():
    if not Path(ZONES_CONFIG).exists():
        return jsonify({"cam_0": {}})
    try:
        with open(ZONES_CONFIG, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/zones/save", methods=["POST"])
def api_zones_save():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "msg": "Invalid JSON"}), 400
    try:
        # Always ensure _meta (authoring resolution) is written
        if not data.get("_meta"):
            try:
                if Path(ZONES_CONFIG).exists():
                    with open(ZONES_CONFIG, encoding="utf-8") as f:
                        existing = json.load(f)
                    if existing.get("_meta"):
                        data["_meta"] = existing["_meta"]
            except Exception:
                pass
            if not data.get("_meta"):
                data["_meta"] = {"w": 960, "h": 540}
        with open(ZONES_CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/zones/delete", methods=["POST"])
def api_zones_delete():
    data    = request.get_json(silent=True) or {}
    zone_id = data.get("zone_id", "").strip()
    cam_key = data.get("cam", "cam_0")
    if not zone_id:
        return jsonify({"ok": False, "msg": "zone_id required"}), 400
    if not Path(ZONES_CONFIG).exists():
        return jsonify({"ok": False, "msg": "No zones config"}), 404
    try:
        with open(ZONES_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.get(cam_key, {}).pop(zone_id, None)
        with open(ZONES_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/zones/clear", methods=["POST"])
def api_zones_clear():
    cam_key = (request.get_json(silent=True) or {}).get("cam", "cam_0")
    try:
        cfg = {}
        if Path(ZONES_CONFIG).exists():
            with open(ZONES_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)
        cfg[cam_key] = {}
        with open(ZONES_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# ── Behaviors CRUD ────────────────────────────────────────────────────────────
@app.route("/api/behaviors")
def api_behaviors_get():
    from behavior_engine import load_behaviors
    return jsonify(load_behaviors())

@app.route("/api/behaviors/save", methods=["POST"])
def api_behaviors_save():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"ok": False, "msg": "Expected JSON array"}), 400
    from behavior_engine import save_behaviors
    try:
        save_behaviors(data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/behaviors/reset", methods=["POST"])
def api_behaviors_reset():
    from behavior_engine import DEFAULT_BEHAVIORS, save_behaviors
    save_behaviors(DEFAULT_BEHAVIORS.copy())
    return jsonify({"ok": True})

# ── Brand ─────────────────────────────────────────────────────────────────────
@app.route("/translations.js")
def serve_translations():
    """Serve translations.js from the app directory"""
    from flask import send_from_directory
    return send_from_directory(APP_DIR, "translations.js", mimetype="application/javascript")


@app.route("/api/brand")
def api_brand():
    return jsonify(load_brand())



@app.route("/api/brand/save", methods=["POST"])
def api_brand_save():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "Invalid JSON"}), 400
    try:
        with open(BRAND_CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# ── Settings ──────────────────────────────────────────────────────────────────
SENSITIVE_KEYS = {"gemini_api_key", "claude_api_key"}

@app.route("/api/settings")
def api_settings():
    with _state_lock:
        # mask API keys in response
        safe = {k: ("***" if k in SENSITIVE_KEYS and v else v)
                for k, v in state.items()}
    return jsonify(safe)

@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.get_json(silent=True) or {}
    with _state_lock:
        for k, v in data.items():
            if k in state:
                if k in SENSITIVE_KEYS and v == "***":
                    continue
                state[k] = v
    return jsonify({"ok": True})

def save_settings_to_disk():
    """Persist state cameras to brand_config for reload on restart"""
    try:
        with _state_lock:
            cams = state.get("cameras", [])
        cfg = load_brand()
        cfg["cameras"] = cams
        with open(BRAND_CONFIG, "w", encoding="utf-8") as f:
            import json as _json
            _json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning("save_settings_to_disk error: %s", e)

# ── Reports ───────────────────────────────────────────────────────────────────
@app.route("/api/activity/summary")
def api_activity_summary():
    date = request.args.get("date", "")
    if not Path(DB_PATH).exists():
        return jsonify({"ok": True, "total": 0, "interested": 0, "alerts": 0, "top_zone": "—", "top_zone_count": 0})
    def q(sql, p=()):
        conn = get_conn(); rows = conn.execute(sql, p).fetchall(); conn.close(); return rows
    where, params = "1=1", []
    if date:
        import datetime
        try:
            d = datetime.date.fromisoformat(date)
            ts0 = datetime.datetime.combine(d, datetime.time.min).timestamp()
            ts1 = datetime.datetime.combine(d, datetime.time.max).timestamp()
            where = "timestamp BETWEEN ? AND ?"; params = [ts0, ts1]
        except Exception: pass
    total = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE {where}", params)[0][0]
    inter = q(f"""SELECT COUNT(DISTINCT person_id) FROM events WHERE {where}
        AND (behavior_id LIKE '%interest%' OR behavior_id LIKE '%tasting%'
          OR behavior_id LIKE '%viewing%' OR behavior_id='interested')""", params)[0][0]
    alrt  = q(f"SELECT COUNT(*) FROM events WHERE {where} AND needs_staff=1", params)[0][0]
    top   = q(f"""SELECT zone_name, COUNT(*) n FROM events WHERE {where} AND zone_name!=''
        GROUP BY zone_name ORDER BY n DESC LIMIT 1""", params)
    zones = q(f"""SELECT zone_name, COUNT(DISTINCT person_id) FROM events
        WHERE {where} AND zone_name!='' GROUP BY zone_name ORDER BY 2 DESC""", params)
    return jsonify({"ok": True, "total": total, "interested": inter,
        "interested_pct": round(inter/total*100) if total else 0,
        "alerts": alrt, "top_zone": top[0][0] if top else "—",
        "top_zone_count": top[0][1] if top else 0,
        "zones": [{"zone": r[0], "visitors": r[1]} for r in zones]})

@app.route("/api/activity")
def api_activity():
    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        date     = request.args.get("date", "")
        behavior = request.args.get("behavior", "")
        zone     = request.args.get("zone", "")
        alert    = request.args.get("alert", "")
        if not Path(DB_PATH).exists():
            return jsonify({"ok": True, "events": [], "total": 0, "pages": 0})
        def q(sql, p=()):
            conn = get_conn(); rows = conn.execute(sql, p).fetchall(); conn.close(); return rows
        where, params = ["1=1"], []
        if date:
            import datetime
            try:
                d = datetime.date.fromisoformat(date)
                ts0 = datetime.datetime.combine(d, datetime.time.min).timestamp()
                ts1 = datetime.datetime.combine(d, datetime.time.max).timestamp()
                where.append("timestamp BETWEEN ? AND ?"); params += [ts0, ts1]
            except Exception: pass
        if behavior: where.append("behavior_id=?"); params.append(behavior)
        if zone:     where.append("zone_name=?");   params.append(zone)
        if alert=="1": where.append("needs_staff=1")
        wsql = " AND ".join(where)
        total = q(f"SELECT COUNT(*) FROM events WHERE {wsql}", params)[0][0]
        pages = max(1, (total + per_page - 1) // per_page)
        offset = (page-1)*per_page
        rows = q(f"""SELECT id, timestamp, person_id, zone_name, behavior_id,
            behavior_name, needs_staff FROM events WHERE {wsql}
            ORDER BY timestamp DESC LIMIT ? OFFSET ?""", params+[per_page, offset])
        import datetime
        events = []
        for r in rows:
            ts = datetime.datetime.fromtimestamp(r[1])
            events.append({"id": r[0], "time": ts.strftime("%H:%M:%S"),
                "date": ts.strftime("%Y-%m-%d"), "person_id": r[2],
                "zone": r[3] or "—", "behavior_id": r[4],
                "behavior": r[5] or r[4] or "—", "alert": bool(r[6])})
        behaviors = [r[0] for r in q(f"SELECT DISTINCT behavior_id FROM events WHERE behavior_id!='' ORDER BY behavior_id")]
        zones_list = [r[0] for r in q(f"SELECT DISTINCT zone_name FROM events WHERE zone_name!='' ORDER BY zone_name")]
        return jsonify({"ok": True, "events": events, "total": total,
            "page": page, "pages": pages, "behaviors": behaviors, "zones": zones_list})
    except Exception as e:
        log.error("api_activity error: %s", e)
        return jsonify({"ok": False, "events": [], "total": 0, "pages": 0})

@app.route("/api/report/pdf")
def api_report_pdf():
    if not Path(DB_PATH).exists():
        return jsonify({"ok": False, "msg": "No database"}), 404
    import tempfile
    tmp = None
    try:
        from report_pdf import build_pdf
        tmp = tempfile.mktemp(suffix=".pdf")
        build_pdf(DB_PATH, request.args.get("date"), tmp)
        with open(tmp, "rb") as f:
            data = f.read()
        return Response(data, mimetype="application/pdf",
                        headers={"Content-Disposition":
                                 "attachment; filename=flowsight_report.pdf"})
    except Exception as e:
        log.error("PDF report error: %s", e)
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

@app.route("/api/report/html")
def api_report_html():
    return jsonify({"ok": False, "msg": "HTML export removed — use PDF export"}), 410

@app.route("/api/insight")
def api_insight():
    if not Path(DB_PATH).exists():
        return jsonify({"ok": False, "msg": "No database"}), 404

    try:
        from ai_insight import get_ai_insight, insight_to_html
        with _state_lock:
            gemini_key = state.get("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
            claude_key = state.get("claude_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        result = get_ai_insight(DB_PATH, request.args.get("date"),
                                api_key=gemini_key or claude_key)
        return jsonify({"ok": result["ok"],
                        "html": insight_to_html(result.get("insight") or
                                                result.get("fallback", "")),
                        "source": result.get("source", "Auto")})
    except Exception as e:
        log.error("Insight error: %s", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

# ── Heat map ────────────────────────────────────────────────────────────────
_heat_engines: dict = {}   # cam_id -> HeatMapEngine

@app.route("/api/heatmap/jpeg")
def api_heatmap_jpeg():
    cam_id = request.args.get("cam", "cam_0")
    engine = _heat_engines.get(cam_id)
    with _cams_lock:
        frame = _cam_frames.get(cam_id)
    if frame is None or engine is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(frame, f"No heatmap data ({cam_id})", (40, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100,100,100), 2)
        _, jpg = cv2.imencode(".jpg", frame)
        return Response(jpg.tobytes(), mimetype="image/jpeg")
    alpha = float(request.args.get("alpha", 0.5))
    data  = engine.get_jpeg(frame, alpha=alpha)
    return Response(data, mimetype="image/jpeg",
                    headers={"Cache-Control":"no-cache,no-store"})

@app.route("/api/heatmap/reset", methods=["POST"])
def api_heatmap_reset():
    cam_id = (request.get_json(silent=True) or {}).get("cam", "cam_0")
    engine = _heat_engines.get(cam_id)
    if engine:
        engine.reset()
    return jsonify({"ok": True})

@app.route("/api/heatmap/zones")
def api_heatmap_zones():
    cam_id = request.args.get("cam", "cam_0")
    if cam_id not in _heat_engines:
        return jsonify([])
    from zones import ZoneManager
    zm    = ZoneManager(ZONES_CONFIG)
    polys = zm.get_polygons(cam_id)
    meta  = zm.get_meta(cam_id)
    scores = _heat_engines[cam_id].get_top_zones(polys)
    result = []
    for zid, score in scores:
        m = meta.get(zid, {})
        result.append({"zone_id": zid, "name": m.get("name", zid),
                        "score": round(score, 2)})
    return jsonify(result)

# ── Demo Image ────────────────────────────────────────────────────────────────
import base64

@app.route("/api/demo/upload", methods=["POST"])
def api_demo_upload():
    """Upload image to use as demo feed instead of RTSP"""
    try:
        f = request.files.get("image")
        if not f:
            return jsonify({"ok": False, "msg": "No file"}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ('.jpg','.jpeg','.png','.bmp'):
            return jsonify({"ok": False, "msg": "Only JPG/PNG allowed"}), 400
        save_path = os.path.join(APP_DIR, "assets", "demo_image" + ext)
        f.save(save_path)
        # Store path in state
        with _state_lock:
            state["demo_image"] = save_path
        log.info("[Demo] Image uploaded: %s", save_path)
        return jsonify({"ok": True, "path": save_path})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/demo/clear", methods=["POST"])
def api_demo_clear():
    """Clear demo image — back to RTSP mode"""
    with _state_lock:
        state["demo_image"] = ""
    # Remove saved demo images
    for ext in ('.jpg','.jpeg','.png','.bmp'):
        p = os.path.join(APP_DIR, "assets", "demo_image" + ext)
        if os.path.exists(p):
            try: os.remove(p)
            except: pass
    log.info("[Demo] Demo image cleared")
    return jsonify({"ok": True})

@app.route("/api/demo/status")
def api_demo_status():
    with _state_lock:
        path = state.get("demo_image", "")
    return jsonify({"active": bool(path), "path": path})

@app.route("/api/push", methods=["POST"])
def api_push():
    secret = os.environ.get("PUSH_SECRET", "")
    if secret and request.headers.get("X-Push-Secret", "") != secret:
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if "hud" in data:
        with hud_lock:
            hud.update(data["hud"])
        with _state_lock:
            state["running"] = data["hud"].get("running", False)
    if "alerts" in data:
        with alerts_lock:
            alerts.extend(data["alerts"])
            del alerts[:-MAX_ALERTS]
    return jsonify({"ok": True})

# ── Web UI ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    try:
        with open(TMPL_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>FlowSight</h1><p>index.html not found. Place it in templates/ or project root.</p>", 500

# ── Detection engine ──────────────────────────────────────────────────────────
def _push_frame(frame: np.ndarray):
    """Non-blocking push — always keep latest frame, drop old ones."""
    _last_frame[0] = frame  # always update last frame
    # Drain queue and put latest
    while True:
        try: frame_q.get_nowait()
        except queue.Empty: break
    try: frame_q.put_nowait(frame)
    except queue.Full: pass

def camera_engine_loop(cam_cfg: dict, stop_event: threading.Event):
    """Per-camera engine loop — runs independently for each camera.

    Each camera thread owns its own YOLO model instance so ByteTrack internal
    state is fully isolated between cameras.  This prevents cross-camera track-ID
    contamination that would corrupt zone assignment in multi-camera setups.
    """
    cam_id   = cam_cfg.get("id", "cam_0")
    cam_name = cam_cfg.get("name", cam_id)
    rtsp     = cam_cfg.get("rtsp_url", "").strip()

    log.info("[Cam:%s] Starting — %s", cam_id, cam_name)

    def set_status(running, msg):
        with _cams_lock:
            _cam_status[cam_id] = {"running": running, "msg": msg}

    try:
        from behavior_engine import BehaviorInferenceEngine
        from tracker import PersonTracker
        from logger import BehaviorLogger
        from alert import check_alert
        from dashboard import draw_overlay, draw_hud
        from zones import ZoneManager
    except Exception as e:
        log.error("[Cam:%s] Import failed: %s", cam_id, e)
        set_status(False, f"Import error: {e}")
        return

    if not rtsp:
        log.error("[Cam:%s] No RTSP URL", cam_id)
        set_status(False, "No RTSP URL")
        return

    log.info("[Cam:%s] Connecting to: %s", cam_id, rtsp[:40] + "...")
    set_status(False, "Connecting...")

    cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # Limit how long cap.read() blocks so the grab thread can exit promptly
    # when stop_event fires.  3 s matches the grab_thread.join() buffer below.
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10_000)   # 10 s to open stream
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC,  3_000)   # 3 s max per frame read
    if not cap.isOpened():
        log.error("[Cam:%s] Cannot open stream", cam_id)
        set_status(False, "Cannot open stream")
        return

    log.info("[Cam:%s] Stream opened OK", cam_id)
    set_status(True, "Running")

    # CPU-only — limit OpenMP threads to avoid context-switch thrash across cameras.
    device = "cpu"
    try:
        import torch
        with _state_lock:
            num_cams = max(1, sum(
                1 for c in state.get("cameras", [{"id": "cam_0"}])
                if c.get("enabled", True)
            ))
        torch.set_num_threads(max(1, os.cpu_count() // num_cams))
        log.info("[Cam:%s] CPU mode — torch threads: %d", cam_id,
                 max(1, os.cpu_count() // num_cams))
    except Exception:
        pass

    try:
        from ultralytics import YOLO
        model = YOLO(MODEL_PATH)
        log.info("[Cam:%s] YOLO loaded on CPU", cam_id)
    except Exception as e:
        log.error("[Cam:%s] YOLO load failed: %s", cam_id, e)
        set_status(False, f"YOLO error: {e}")
        cap.release()
        return

    # Resolve ByteTracker config — use the tuned local copy
    bt_yaml = os.path.join(APP_DIR, "bytetrack.yaml")
    if not os.path.exists(bt_yaml):
        bt_yaml = "bytetrack.yaml"
    log.info("[Cam:%s] Tracker config: %s", cam_id, bt_yaml)

    tracker  = PersonTracker()
    engine   = BehaviorInferenceEngine(ZONES_CONFIG, BEHS_CONFIG)
    logger   = BehaviorLogger(DB_PATH)
    zm       = ZoneManager(ZONES_CONFIG)
    from heatmap import HeatMapEngine
    # Use actual frame resolution so person coordinates aren't clipped
    _fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    _fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or 1280
    _heat_engines[cam_id] = HeatMapEngine(width=_fw, height=_fh, decay=0.998)
    heat_eng = _heat_engines[cam_id]

    import time as _time
    from collections import Counter

    RECONNECT_INTERVAL = 5
    CLEANUP_EVERY      = 150   # flush stale state every ~10 s at 15 fps
    fail_count = 0
    MAX_FAILS  = 30
    frame_no   = 0

    # ── Dedicated frame-grabber thread ────────────────────────────────────
    # Drains the RTSP buffer continuously so the inference loop always gets
    # the latest frame instead of a buffered one.
    _latest_frame = [None]
    _frame_lock   = threading.Lock()
    _grab_stop    = threading.Event()

    def _grab_loop():
        nonlocal cap, fail_count
        while not _grab_stop.is_set() and not stop_event.is_set():
            ret, frame = cap.read()
            if ret:
                with _frame_lock:
                    _latest_frame[0] = frame
                fail_count = 0
            else:
                fail_count += 1
                _time.sleep(0.01)

    grab_thread = threading.Thread(target=_grab_loop, daemon=True,
                                   name=f"grab_{cam_id}")
    grab_thread.start()
    _time.sleep(0.5)   # give grabber time to fill the first frame

    # ── Main inference loop ───────────────────────────────────────────────
    while not stop_event.is_set():
        with _frame_lock:
            frame = _latest_frame[0]

        if frame is None:
            _time.sleep(0.05)
            continue

        # Reconnect on persistent read failures
        if fail_count >= MAX_FAILS:
            log.warning("[Cam:%s] Too many failures — reconnecting", cam_id)
            _grab_stop.set()
            grab_thread.join(timeout=3.0)
            cap.release()
            _time.sleep(RECONNECT_INTERVAL)
            cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10_000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC,  3_000)
            fail_count = 0
            _grab_stop.clear()
            _latest_frame[0] = None
            if not cap.isOpened():
                set_status(False, "Reconnect failed")
                continue
            grab_thread = threading.Thread(target=_grab_loop, daemon=True,
                                           name=f"grab_{cam_id}")
            grab_thread.start()
            set_status(True, "Reconnected")
            _time.sleep(0.5)
            continue

        # Re-read settings on every iteration so UI changes take effect
        # immediately without restarting the camera.
        with _state_lock:
            conf = state.get("conf", 0.40)
            anon = state.get("anonymize", True)

        frame_no += 1
        fh, fw = frame.shape[:2]

        try:
            # ── Detection + tracking ──────────────────────────────────────
            # imgsz=1280: halves the downscale on 1080p cameras (3× → 1.5×),
            #             making distant/small people reliably detectable.
            # tracker=bt_yaml: uses the tuned track_buffer=300 (20 s) so
            #             occlusions up to 20 s are bridged without new IDs.
            # cam_key: namespaces trajectory keys to prevent state collision
            #          between cameras.
            # imgsz: user can override via settings; auto-select otherwise.
            # CPU: scale down with camera count to maintain ≥5fps per camera.
            with _state_lock:
                _imgsz = state.get("imgsz", 0)
                _ncams = max(1, sum(
                    1 for c in state.get("cameras", [{"id": "cam_0"}])
                    if c.get("enabled", True)
                ))
            if _imgsz <= 0:
                _imgsz = 1280 if _ncams <= 2 else (960 if _ncams <= 4 else 640)

            # No lock needed — each camera has its own model instance so
            # ByteTrack state is fully isolated and concurrent calls are safe.
            results = model.track(
                source=frame,
                persist=True,
                conf=conf,
                classes=[0],
                imgsz=_imgsz,
                device="cpu",
                half=False,
                tracker=bt_yaml,
                verbose=False,
            )
            people = tracker.update(results[0], cam_key=cam_id) if results else []
            states: dict = {}   # keyed by state_key — draw_overlay/draw_hud expect dict
            polys  = zm.get_polygons(cam_id)
            meta   = zm.get_meta(cam_id)

            # ── Behaviour inference ───────────────────────────────────────
            # frame_w/frame_h are passed into infer() so zone polygons
            # (authored at 960×540) are scaled to native frame coordinates
            # before the point-in-polygon test.
            for person in people:
                st = engine.infer(person, cam_id, frame_w=fw, frame_h=fh)
                states[person["state_key"]] = st   # dict so draw_overlay.get() works
                zone_display = meta.get(st.zone, {}).get("name", st.zone)
                logger.log(st, cam_id, zone_display)
                check_alert(st, cam_id)
                # Debug: log zone + behavior every 30 frames so you can verify detection
                if frame_no % 30 == 0:
                    cx, cy = person["center"]
                    log.debug("[Cam:%s] id=%s center=(%d,%d) zone=%s cat=%s beh=%s dwell=%.1fs",
                              cam_id, person["id"], cx, cy, st.zone, st.zone_cat,
                              st.behavior_id, (time.monotonic() - st.dwell_start))

            # ── Periodic cleanup + live config reload ────────────────────
            if frame_no % CLEANUP_EVERY == 0:
                active = {p["state_key"] for p in people}
                tracker.cleanup(active)
                engine.cleanup_stale(active)
                from alert import clear_stale_alerts
                clear_stale_alerts()
                # Reload behaviors and zones so UI changes take effect without restart
                engine.reload_behaviors()
                zm = ZoneManager(ZONES_CONFIG)

            # ── Per-zone headcount ────────────────────────────────────────
            zone_counts = Counter(
                s.zone for s in states.values()
                if not s.is_staff and s.zone != "floor"
            )

            # ── Annotate display frame ────────────────────────────────────
            annotated = draw_overlay(frame.copy(), people, states, polys, meta, anon)
            annotated = draw_hud(annotated, cam_id, states)

            # ── Publish results ───────────────────────────────────────────
            with _cams_lock:
                _cam_frames[cam_id] = annotated
                _cam_huds[cam_id]   = {
                    "cust":   sum(1 for s in states.values() if not s.is_staff),
                    "seller": sum(1 for s in states.values() if s.is_staff),
                    "alert":  sum(1 for s in states.values() if s.needs_staff),
                    "zones":  dict(zone_counts),
                }
            _last_frame[0] = annotated

            # ── Heatmap update (pass person dicts, not PersonState) ───────
            heat_eng.update(people)

        except Exception as e:
            log.error("[Cam:%s] inference error: %s", cam_id, e)
            with _cams_lock:
                # Never publish the raw frame — blur it so faces aren't shown
                _cam_frames[cam_id] = cv2.GaussianBlur(frame, (99, 99), 0)

    # Signal the grab thread and wait for it to finish.
    # Timeout = READ_TIMEOUT_MSEC (3 s) + 2 s buffer so cap.release() is
    # never called while grab is still inside cap.read().
    _grab_stop.set()
    grab_thread.join(timeout=5.0)
    if grab_thread.is_alive():
        log.warning("[Cam:%s] Grab thread still alive after 5 s — forcing cap release", cam_id)
    cap.release()
    cap = None   # prevent any stale reference from reusing the handle
    logger.close()
    set_status(False, "Stopped")
    log.info("[Cam:%s] Stopped", cam_id)

def engine_loop():
    import datetime
    log.info("[Engine] Starting engine_loop...")
    try:
        from behavior_engine import BehaviorInferenceEngine
        from tracker import PersonTracker
        from logger import BehaviorLogger
        from alert import check_alert
        from dashboard import draw_overlay, draw_hud
        from zones import ZoneManager
        log.info("[Engine] All modules imported OK")
    except Exception as e:
        log.error("[Engine] Import failed: %s", e)
        import traceback
        log.error(traceback.format_exc())
        with _state_lock:
            state["running"] = False
        return

    with _state_lock:
        rtsp  = state.get("rtsp_url", "")
        demo  = state.get("demo_image", "")

    # Demo image mode — no camera needed
    if demo and os.path.exists(demo):
        log.info("[Engine] Demo image mode: %s", demo)
        _demo_frame = cv2.imread(demo)
        if _demo_frame is not None:
            h, w = _demo_frame.shape[:2]
            if w > 1280:
                _demo_frame = cv2.resize(_demo_frame, (1280, int(h*1280/w)))
            _last_frame[0] = _demo_frame
        # Run fake loop — just keep running state alive
        import time as _time
        while not stop_evt.is_set():
            if _demo_frame is not None:
                _last_frame[0] = _demo_frame
                _push_frame(_demo_frame)
            _time.sleep(0.1)
        with _state_lock:
            state["running"] = False
        log.info("[Engine] Demo mode stopped")
        return

    if not rtsp:
        log.error("[Engine] No RTSP URL — set it in Settings then Start again")
        with _state_lock:
            state["running"] = False
        return

    log.info("[Engine] Connecting to: %s", rtsp[:40]+"...")
    cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        log.error("[Engine] Cannot open stream — check RTSP URL and camera network")
        with _state_lock:
            state["running"] = False
        return
    log.info("[Engine] Stream opened OK")

    nonlocal_device = ["cpu"]

    # Load YOLO — CPU only
    try:
        from ultralytics import YOLO
        _mp = "yolov8n.pt"
        for _p in [MODEL_PATH, os.path.join(APP_DIR,"yolov8n.pt"),
                   os.path.join(APP_DIR,"_internal","yolov8n.pt")]:
            if os.path.exists(_p):
                _mp = _p
                break
        log.info("[Engine] Loading YOLO: %s", _mp)
        model = YOLO(_mp)
        model.to("cpu")
        log.info("[Engine] YOLO ready on CPU")

        # Resolve ByteTracker config — prefer a local copy alongside the exe/script
        _bt_local = os.path.join(APP_DIR, "bytetrack.yaml")
        _bt_yaml  = _bt_local if os.path.exists(_bt_local) else "bytetrack.yaml"
        log.info("[Engine] Tracker config: %s", _bt_yaml)
    except Exception as e:
        import traceback
        log.error("[Engine] YOLO failed: %s", e)
        log.error(traceback.format_exc())
        cap.release()
        with _state_lock:
            state["running"] = False
        return

    tracker = PersonTracker()
    engine  = BehaviorInferenceEngine(ZONES_CONFIG, BEHS_CONFIG)
    logger  = BehaviorLogger(DB_PATH)
    zm      = ZoneManager(ZONES_CONFIG)
    frame_no = 0
    cleanup_every = 150

    # Init heat map engine
    global _heat_engine
    from heatmap import HeatMapEngine
    _heat_engine = HeatMapEngine(decay=0.998)

    log.info("[Engine] Entering detection loop...")
    try:
        _frame_ok = False
        while not stop_evt.is_set():
            ret, frame = cap.read()
            if not ret:
                log.warning("[Engine] Stream read failed — reconnecting in 2s...")
                time.sleep(2)
                cap.release()
                cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    log.error("[Engine] Reconnect failed")
                    time.sleep(5)
                continue

            if not _frame_ok:
                log.info("[Engine] First frame received OK shape=%s", frame.shape)
                _frame_ok = True

            frame_no += 1

            # Resize for display and push immediately so stream shows
            h_r, w_r = frame.shape[:2]
            display_frame = (cv2.resize(frame, (1280, int(h_r * 1280 / w_r)))
                             if w_r > 1280 else frame.copy())
            _last_frame[0] = display_frame
            _push_frame(display_frame)

            # Process every 3rd frame to reduce load
            if frame_no % 3 != 0:
                continue

            if frame_no == 3:
                log.info("[Engine] Starting first detection (frame 3)...")

            # Auto-adjust confidence for bright daytime
            hour = datetime.datetime.now().hour
            with _state_lock:
                base_conf = state["conf"]
            conf = max(0.15, base_conf - 0.10) if 10 <= hour <= 16 else base_conf

            try:
                if frame_no == 3:
                    log.info("[Engine] Calling model.track()...")
                _raw = model.track(
                    frame, classes=[0], conf=conf,
                    tracker=_bt_yaml, persist=True, verbose=False)
                if not _raw or len(_raw) == 0:
                    continue
                results = _raw[0]
                if frame_no == 3:
                    log.info("[Engine] model.track() OK")
            except Exception as e:
                import traceback
                log.error("[Engine] Track error: %s", e)
                log.error(traceback.format_exc())
                continue

            try:
                persons = tracker.update(results)
            except Exception as e:
                import traceback
                log.error("[Engine] tracker.update() crash: %s", e)
                log.error(traceback.format_exc())
                continue

            if frame_no % cleanup_every == 0:
                active = {p["state_key"] for p in persons}
                tracker.cleanup(active)

            try:
                engine.reload_behaviors()
            except Exception as e:
                log.error("[Engine] reload_behaviors() crash: %s", e)

            states = {}
            n_cust = n_staff = n_alert = 0
            now_str = datetime.datetime.now().strftime("%H:%M")

            for person in persons:
                try:
                    st = engine.infer(person, "cam_0")
                    states[person["state_key"]] = st
                    zone_meta = zm.get_meta("cam_0").get(st.zone, {})
                    zone_display_name = zone_meta.get("name", st.zone)
                    logger.log(st, "cam_0", zone_display_name)
                    check_alert(st, "cam_0")

                    if st.needs_staff and not st.is_staff:
                        n_alert += 1
                        with alerts_lock:
                            alerts.append({
                                "time": now_str,
                                "person": st.person_id,
                                "zone": zone_display_name,
                                "behavior": st.behavior_name,
                                "behavior_id": st.behavior_id,
                            })
                            if len(alerts) > MAX_ALERTS:
                                del alerts[:-MAX_ALERTS]

                    if st.is_staff:
                        n_staff += 1
                    else:
                        n_cust += 1
                except Exception as e:
                    import traceback
                    log.error("[Engine] person inference crash pid=%s: %s", person.get("id"), e)
                    log.error(traceback.format_exc())

            with hud_lock:
                hud.update({"running": True, "cust": n_cust,
                            "seller": n_staff, "alert": n_alert})

            if _heat_engine is not None:
                try:
                    _heat_engine.update(persons)
                    heat_frame[0] = display_frame.copy()
                except Exception:
                    pass

            try:
                polys   = zm.get_polygons("cam_0")
                meta    = zm.get_meta("cam_0")
                h_d, w_d = frame.shape[:2]
                annotated = (cv2.resize(frame.copy(), (1280, int(h_d * 1280 / w_d)))
                             if w_d > 1280 else frame.copy())
                with _state_lock:
                    anon = state.get("anonymize", False)
                annotated = draw_overlay(annotated, persons, states, polys, meta,
                                         anonymize=anon)
                annotated = draw_hud(annotated, "cam_0", states)
                _push_frame(annotated)
            except Exception as e:
                import traceback
                log.error("[Engine] draw/push crash: %s", e)
                log.error(traceback.format_exc())
                # Still push raw frame so stream doesn't go black
                _push_frame(display_frame)


    except Exception as e:
        import traceback
        log.error("[Engine] FATAL crash in detection loop: %s", e)
        log.error(traceback.format_exc())
    finally:
        cap.release()
        logger.close()
        with hud_lock:
            hud["running"] = False
        with _state_lock:
            state["running"] = False
        log.info("[Engine] Stopped")

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    brand = load_brand()
    print(f"\n{'='*52}")
    print(f"  {brand['name']} — {brand.get('tagline', '')}")
    print(f"  http://localhost:5000")
    print(f"{'='*52}\n")

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
