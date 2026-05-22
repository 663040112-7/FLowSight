# FlowSight — Build Installer Guide

## ขั้นตอนทำ Installer

### Step 1 — Download Python Embedded
ดาวน์โหลดจาก python.org:
https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip

แตกไฟล์ไปที่:
```
D:\Work\WIne AI\flowsight\installer\python_embedded\
```

### Step 2 — แก้ python312._pth
เปิดไฟล์ `python_embedded\python312._pth` แก้เป็น:
```
python312.zip
.
Scripts\site-packages
import site
```
(uncomment บรรทัด `import site`)

### Step 3 — ติดตั้ง Inno Setup
ดาวน์โหลดจาก: https://jrsoftware.org/isdl.php

### Step 4 — Build Installer
1. เปิด Inno Setup Compiler
2. Open file: `D:\Work\WIne AI\flowsight\installer\setup.iss` 
   (หรือ `D:\Work\WIne AI\flowsight\setup.iss`)
3. กด Build → Compile (หรือ Ctrl+F9)
4. รอจนเสร็จ

### Step 5 — ผลลัพธ์
ได้ไฟล์: `D:\Work\WIne AI\flowsight\installer_output\FlowSight_Setup_v1.0.exe`

---

## วิธีใช้งาน (สำหรับลูกค้า)
1. ดับเบิลคลิก `FlowSight_Setup_v1.0.exe`
2. กด Next → Next → Install
3. รอ 3-5 นาที (ติดตั้ง packages อัตโนมัติ)
4. กด Finish → FlowSight เปิดขึ้นมาเอง
5. ครั้งต่อไปดับเบิลคลิก shortcut บน Desktop

---

## หมายเหตุ
- ลูกค้าไม่ต้องติดตั้ง Python หรือ package ใดๆ เอง
- ต้องการ internet ครั้งแรกเท่านั้น (download packages ~1.5GB)
- ครั้งต่อไปไม่ต้อง internet
