# =============================================================================
# server.py — FlowSight Generic Retail AI  v1.1 (reviewed & fixed)
# =============================================================================
import sys, os, time, json, queue, threading, base64, sqlite3, logging
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

# ── Logging ───────────────────────────────────────────────────────────────────
# Log to file when running as .exe (no console in --windowed mode)
log_handlers = [logging.StreamHandler()]
if getattr(sys, "frozen", False):
    log_file = os.path.join(APP_DIR, "flowsight.log")
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
DB_PATH      = os.path.join(APP_DIR, "behavior_log.db")
ZONES_CONFIG = os.path.join(APP_DIR, "zones_config.json")
BEHS_CONFIG  = os.path.join(APP_DIR, "behaviors_config.json")
BRAND_CONFIG = os.path.join(APP_DIR, "brand_config.json")
MODEL_PATH   = os.path.join(APP_DIR, "yolov8n.pt")
TMPL_PATH    = os.path.join(APP_DIR, "templates", "index.html")
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
    "conf": 0.25,
    "anonymize": False,
    "dwell_interested": 25,
    "dwell_loitering": 90,
    "dwell_checkout_min": 5,
    "dwell_seating_waiting": 180,
    "gemini_api_key": "",
    "claude_api_key": "",
}

frame_q    = queue.Queue(maxsize=3)
heat_frame: list = [None]      # last frame for heat map overlay
stop_evt   = threading.Event()
eng_thread = None

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

@app.route("/api/frame")
def api_frame():
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

# ── Engine control ────────────────────────────────────────────────────────────
@app.route("/api/start", methods=["POST"])
def api_start():
    global eng_thread
    if CLOUD_MODE:
        return jsonify({"ok": False, "msg": "Cloud mode — no local camera"})

    # Force-reset running state if engine thread is dead
    with _state_lock:
        if state["running"]:
            # Check if engine thread is actually still alive
            if eng_thread is not None and eng_thread.is_alive():
                return jsonify({"ok": False, "msg": "Already running"})
            else:
                # Thread died — reset state so we can restart
                state["running"] = False
                log.warning("[API] Engine thread died — resetting state")

        if not state["rtsp_url"]:
            return jsonify({"ok": False, "msg": "No RTSP URL configured"})

        stop_evt.clear()
        # Clear stale frames from queue
        while not frame_q.empty():
            try: frame_q.get_nowait()
            except: break

        eng_thread = threading.Thread(target=engine_loop, daemon=True,
                                      name="engine")
        eng_thread.start()
        state["running"] = True
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_evt.set()
    with _state_lock:
        state["running"] = False
    with hud_lock:
        hud["running"] = False
    # Wait briefly for engine thread to finish
    if eng_thread and eng_thread.is_alive():
        eng_thread.join(timeout=3.0)
    # Clear queue so next start is clean
    while not frame_q.empty():
        try:
            frame_q.get_nowait()
        except Exception:
            break
    return jsonify({"ok": True})

@app.route("/api/hud")
def api_hud():
    with hud_lock:
        h = dict(hud)
    with _state_lock:
        h["running"] = state["running"]
    return jsonify(h)

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
                # don't overwrite key with masked value
                if k in SENSITIVE_KEYS and v == "***":
                    continue
                state[k] = v
    return jsonify({"ok": True})

# ── Reports ───────────────────────────────────────────────────────────────────
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
_heat_engine = None

@app.route("/api/heatmap/jpeg")
def api_heatmap_jpeg():
    global _heat_engine
    frame = heat_frame[0]
    if frame is None or _heat_engine is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(frame, "No heatmap data yet", (80, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100,100,100), 2)
        _, jpg = cv2.imencode(".jpg", frame)
        return Response(jpg.tobytes(), mimetype="image/jpeg")
    alpha = float(request.args.get("alpha", 0.5))
    data  = _heat_engine.get_jpeg(frame, alpha=alpha)
    return Response(data, mimetype="image/jpeg",
                    headers={"Cache-Control":"no-cache,no-store"})

@app.route("/api/heatmap/reset", methods=["POST"])
def api_heatmap_reset():
    global _heat_engine
    if _heat_engine:
        _heat_engine.reset()
    return jsonify({"ok": True})

@app.route("/api/heatmap/zones")
def api_heatmap_zones():
    global _heat_engine
    if _heat_engine is None:
        return jsonify([])
    from zones import ZoneManager
    zm    = ZoneManager(ZONES_CONFIG)
    polys = zm.get_polygons("cam_0")
    meta  = zm.get_meta("cam_0")
    scores = _heat_engine.get_top_zones(polys)
    result = []
    for zid, score in scores:
        m = meta.get(zid, {})
        result.append({"zone_id": zid, "name": m.get("name", zid),
                        "score": round(score, 2)})
    return jsonify(result)

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
        return "<h1>FlowSight</h1><p>templates/index.html not found</p>", 500

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
        rtsp = state.get("rtsp_url", "")
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

    nonlocal_device = ["cpu"]  # mutable container for scope sharing
    _device = "cpu"

    # Load YOLO
    try:
        from ultralytics import YOLO
        _mp = "yolov8n.pt"
        for _p in [MODEL_PATH, os.path.join(APP_DIR,"yolov8n.pt"),
                   os.path.join(APP_DIR,"_internal","yolov8n.pt")]:
            if os.path.exists(_p):
                _mp = _p
                break
        log.info("[Engine] Loading YOLO: %s", _mp)
        import torch
        # Force CPU when running as frozen .exe — CUDA unstable in PyInstaller
        if getattr(sys, "frozen", False):
            _device = "cpu"
            log.info("[Engine] .exe mode — using CPU (stable)")
        elif load_brand().get("force_cpu", False):
            _device = "cpu"
            log.info("[Engine] force_cpu=True — using CPU")
        elif torch.cuda.is_available():
            _device = "cuda"
        else:
            _device = "cpu"
        nonlocal_device[0] = _device
        model = YOLO(_mp)
        model.to(_device)
        log.info("[Engine] YOLO ready on %s", _device.upper())
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

            # Clear CUDA cache every 100 frames
            if frame_no % 100 == 0 and nonlocal_device[0] == "cuda":
                try:
                    import torch
                    torch.cuda.empty_cache()
                    if frame_no % 500 == 0:
                        mem = torch.cuda.memory_allocated() / 1024**2
                        log.info("[Engine] GPU memory: %.1f MB (frame %d)", mem, frame_no)
                except Exception:
                    pass

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

    try:
        from license import check_or_activate, get_hwid
        hwid   = get_hwid()
        result = check_or_activate()
        if result["valid"]:
            days     = result.get("days_left", 9999)
            days_str = f"{days} days left" if days < 9999 else "Perpetual"
            print(f"  ✅ License: Valid ({days_str})\n")
        else:
            print(f"  ⚠  License: {result['msg']}")
            print(f"  ⚠  HWID: {hwid}")
            print(f"  ⚠  Run: python activate.py\n")
    except Exception as e:
        log.warning("License check skipped: %s", e)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
