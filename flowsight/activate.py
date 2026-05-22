# =============================================================================
# activate.py — FlowSight License Activation Tool (รันบนเครื่องลูกค้า)
# =============================================================================
import sys, json
from pathlib import Path
from license import get_hwid, validate_license, save_license, LICENSE_FILE

def main():
    print("=" * 55)
    print("  FlowSight — License Activation")
    print("=" * 55)

    hwid = get_hwid()
    print(f"\n  Hardware ID: {hwid}")
    print("  (ส่ง Hardware ID นี้ให้ผู้ขายเพื่อรับ License Key)\n")

    # ถ้ามี license แล้ว
    if Path(LICENSE_FILE).exists():
        try:
            with open(LICENSE_FILE) as f:
                data = json.load(f)
            result = validate_license(data.get("key",""), hwid)
            if result["valid"]:
                print(f"  Status   : ✅ Active")
                print(f"  Customer : {data.get('customer','')}")
                if result["days_left"] < 9999:
                    print(f"  Expires  : {result['days_left']} days left")
                else:
                    print(f"  Expires  : Never (perpetual)")
                print("\n  License is valid. No action needed.")
                return
            else:
                print(f"  Status: ❌ {result['msg']}")
        except Exception:
            print("  Status: ❌ License file corrupted")

    # ขอ key ใหม่
    print("  Enter your license key (or press Enter to run in trial mode):")
    key = input("  Key: ").strip()
    if not key:
        print("\n  Running in trial mode — some features may be limited.")
        return

    result = validate_license(key, hwid)
    if result["valid"]:
        # parse expiry จาก license file ถ้ามี หรือตั้ง default 1 ปี
        import time
        expiry = int(time.time()) + 365 * 86400
        save_license(key, hwid, expiry)
        print(f"\n  ✅ Activated successfully!")
        print(f"  Days remaining: {result['days_left']}")
    else:
        print(f"\n  ❌ Activation failed: {result['msg']}")
        print("  Please contact your vendor with the Hardware ID above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
