# =============================================================================
# license.py — FlowSight Hardware ID Licensing System
# =============================================================================
import hashlib, uuid, json, os, time
from pathlib import Path

LICENSE_FILE = "license.key"
PRODUCT_ID   = "FLOWSIGHT-2026"

def get_hwid() -> str:
    """สร้าง Hardware ID จาก MAC address + machine name"""
    mac  = uuid.getnode()
    name = os.environ.get("COMPUTERNAME", os.uname().nodename if hasattr(os,"uname") else "PC")
    raw  = f"{PRODUCT_ID}:{mac}:{name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20].upper()

def generate_license(hwid: str, customer: str = "", days: int = 365) -> str:
    """สร้าง license key จาก HWID (ใช้ฝั่ง vendor)"""
    secret   = "FS2026SECRET"  # เปลี่ยนก่อน deploy
    expiry   = int(time.time()) + days * 86400
    payload  = f"{hwid}:{expiry}:{customer}"
    sig      = hashlib.sha256(f"{secret}:{payload}".encode()).hexdigest()[:12].upper()
    # format: XXXX-XXXX-XXXX-XXXX-SIG
    h = hashlib.md5(payload.encode()).hexdigest().upper()
    key = f"{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}-{sig}"
    return key

def validate_license(key: str, hwid: str) -> dict:
    """
    ตรวจสอบ license key
    คืน {"valid": bool, "msg": str, "days_left": int}
    """
    if not Path(LICENSE_FILE).exists():
        return {"valid": False, "msg": "No license file found", "days_left": 0}
    try:
        with open(LICENSE_FILE) as f:
            data = json.load(f)
    except Exception:
        return {"valid": False, "msg": "License file corrupted", "days_left": 0}

    stored_key  = data.get("key", "")
    stored_hwid = data.get("hwid", "")
    expiry      = data.get("expiry", 0)

    if stored_key != key:
        return {"valid": False, "msg": "Invalid license key", "days_left": 0}
    if stored_hwid != hwid:
        return {"valid": False, "msg": "License locked to different machine", "days_left": 0}
    now = int(time.time())
    if expiry != 0 and now > expiry:
        return {"valid": False, "msg": "License expired", "days_left": 0}

    days_left = max(0, (expiry - now) // 86400) if expiry != 0 else 9999
    return {"valid": True, "msg": "License valid", "days_left": days_left}

def save_license(key: str, hwid: str, expiry: int, customer: str = ""):
    data = {"key": key, "hwid": hwid, "expiry": expiry, "customer": customer}
    with open(LICENSE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def check_or_activate(key: str = None) -> dict:
    """
    ตรวจสอบ license ตอน startup
    ถ้ายังไม่มี license file → ลองใช้ key ที่ส่งมา
    """
    hwid = get_hwid()

    # ถ้ามี license file แล้ว
    if Path(LICENSE_FILE).exists():
        try:
            with open(LICENSE_FILE) as f:
                data = json.load(f)
            return validate_license(data.get("key",""), hwid)
        except Exception:
            pass

    # ถ้ายังไม่มี และส่ง key มา
    if key:
        result = validate_license(key, hwid)
        return result

    # Trial mode — ไม่มี license
    return {"valid": False, "msg": "No license", "days_left": 0}


# ── Vendor tool: สร้าง license key ──────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FlowSight License Generator")
    parser.add_argument("--hwid",     help="Hardware ID ของลูกค้า")
    parser.add_argument("--customer", default="", help="ชื่อลูกค้า")
    parser.add_argument("--days",     type=int, default=365, help="จำนวนวัน")
    parser.add_argument("--get-hwid", action="store_true", help="แสดง HWID เครื่องนี้")
    args = parser.parse_args()

    if args.get_hwid:
        print(f"HWID: {get_hwid()}")
    elif args.hwid:
        key    = generate_license(args.hwid, args.customer, args.days)
        expiry = int(time.time()) + args.days * 86400
        print(f"\nLicense Key : {key}")
        print(f"HWID        : {args.hwid}")
        print(f"Customer    : {args.customer}")
        print(f"Days        : {args.days}")
        print(f"Expires     : {time.strftime('%Y-%m-%d', time.localtime(expiry))}")
        # บันทึกลงไฟล์ให้เลย
        save_license(key, args.hwid, expiry, args.customer)
        print(f"Saved       : {LICENSE_FILE}")
    else:
        parser.print_help()
