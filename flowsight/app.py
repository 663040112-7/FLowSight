# =============================================================================
# app.py — FlowSight Desktop Entry Point
# =============================================================================
import sys, os, threading, time, subprocess, webbrowser

# Fix paths
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_DIR)

# Must add APP_DIR to path so server.py can be found
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

PORT = 5000

def start_flask():
    from server import app
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=PORT,
            debug=False, threaded=True, use_reloader=False)

def wait_for_server(timeout=20) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}", timeout=1)
            return True
        except Exception:
            time.sleep(0.15)
    return False

def get_brand():
    try:
        import json
        with open(os.path.join(APP_DIR, "brand_config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"name": "FlowSight"}

def open_browser(url: str):
    browsers = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for browser in browsers:
        if os.path.exists(browser):
            subprocess.Popen([browser, f"--app={url}",
                              "--window-size=1360,820",
                              "--disable-extensions", "--no-first-run"])
            return True
    webbrowser.open(url)
    return False

def main():
    brand    = get_brand()
    app_name = brand.get("name", "FlowSight")

    t = threading.Thread(target=start_flask, daemon=True)
    t.start()

    print(f"Starting {app_name}...")
    if not wait_for_server():
        print("ERROR: Server failed to start")
        sys.exit(1)
    print(f"{app_name} ready")

    url = f"http://127.0.0.1:{PORT}"
    open_browser(url)

    print(f"\n{app_name} running at {url}")
    print("Press Ctrl+C to stop\n")
    try:
        t.join()
    except KeyboardInterrupt:
        print(f"\n{app_name} stopped")

if __name__ == "__main__":
    main()
