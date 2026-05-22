# =============================================================================
# vendor_tools.py — FlowSight Vendor License Management
# ใช้ฝั่งผู้ขาย (ไม่แจกให้ลูกค้า)
# =============================================================================
import hashlib, time, json, sys
from license import get_hwid, generate_license, save_license

def print_header():
    print("\n" + "="*55)
    print("  FlowSight — Vendor License Tool")
    print("="*55 + "\n")

def create_license_interactive():
    print_header()
    hwid     = input("  HWID ของลูกค้า: ").strip()
    customer = input("  ชื่อลูกค้า/ร้าน: ").strip()
    days_str = input("  จำนวนวัน (default 365): ").strip()
    days     = int(days_str) if days_str.isdigit() else 365

    if not hwid:
        print("  ❌ กรุณาใส่ HWID")
        return

    key    = generate_license(hwid, customer, days)
    expiry = int(time.time()) + days * 86400

    print(f"\n  {'─'*50}")
    print(f"  License Key : {key}")
    print(f"  HWID        : {hwid}")
    print(f"  Customer    : {customer}")
    print(f"  Days        : {days}")
    print(f"  Expires     : {time.strftime('%Y-%m-%d', time.localtime(expiry))}")
    print(f"  {'─'*50}")
    print(f"\n  ✅ ส่ง License Key นี้ให้ลูกค้า")
    print(f"  ลูกค้ารัน: python activate.py แล้วใส่ key\n")

    # บันทึก log
    log = {"hwid": hwid, "customer": customer, "key": key,
           "days": days, "created": time.strftime("%Y-%m-%d")}
    try:
        existing = []
        try:
            with open("vendor_license_log.json") as f:
                existing = json.load(f)
        except Exception:
            pass
        existing.append(log)
        with open("vendor_license_log.json","w") as f:
            json.dump(existing, f, indent=2)
        print(f"  Saved to vendor_license_log.json")
    except Exception as e:
        print(f"  Warning: Could not save log: {e}")


def list_licenses():
    print_header()
    try:
        with open("vendor_license_log.json") as f:
            licenses = json.load(f)
        print(f"  {'Customer':<25} {'HWID':<22} {'Days':<6} {'Created'}")
        print(f"  {'─'*70}")
        for lic in licenses:
            print(f"  {lic.get('customer',''):<25} {lic.get('hwid',''):<22} {lic.get('days',''):<6} {lic.get('created','')}")
        print(f"\n  Total: {len(licenses)} licenses")
    except FileNotFoundError:
        print("  No licenses created yet.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_licenses()
    else:
        create_license_interactive()
