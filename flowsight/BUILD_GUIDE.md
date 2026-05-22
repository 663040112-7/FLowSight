# FlowSight — Build & Distribution Guide

## ขั้นตอนการ build และแจกจ่าย

### Step 1 — ทดสอบก่อน build
```bash
python server.py
# เปิด http://localhost:5000 ทดสอบทุก feature
```

### Step 2 — ติดตั้ง build tools
```bash
pip install pyinstaller pyarmor
```

### Step 3 — Protect code (ป้องกัน copy)
```
ดับเบิลคลิก protect.bat
```
ไฟล์ protected จะอยู่ใน `dist/`

### Step 4 — Build .exe
```
ดับเบิลคลิก build_installer.bat
```
ได้ไฟล์ `dist/FlowSight/FlowSight.exe`

### Step 5 — Build Installer
1. ดาวน์โหลด Inno Setup จาก https://jrsoftware.org/isinfo.php
2. เปิด `setup.iss`
3. กด Build → Compile
4. ได้ไฟล์ `installer_output/FlowSight_Setup_v1.0.exe`

---

## ระบบ License

### ฝั่งลูกค้า — ขอ HWID
```bash
python activate.py
# จะแสดง Hardware ID ของเครื่อง
# ส่ง ID นี้ให้ผู้ขาย
```

### ฝั่งผู้ขาย — สร้าง License Key
```bash
python vendor_tools.py
# ใส่ HWID ของลูกค้า + ชื่อร้าน + จำนวนวัน
# ได้ License Key → ส่งให้ลูกค้า
```

### ฝั่งลูกค้า — Activate
```bash
python activate.py
# ใส่ License Key ที่ได้รับ
# ✅ Activated!
```

---

## โครงสร้างไฟล์แจกลูกค้า

```
FlowSight_Setup_v1.0.exe  ← installer
└── (ติดตั้งแล้วจะได้)
    FlowSight.exe           ← รันหลัก
    activate.py             ← activate license
    templates/
    static/
    bytetrack.yaml
    brand_config.json
    behaviors_config.json
```

## ไฟล์ที่ไม่แจกลูกค้า (เก็บไว้ฝั่งผู้ขาย)
- `vendor_tools.py` — สร้าง license
- `vendor_license_log.json` — log ลูกค้า
- source code ทุกไฟล์ `.py`
