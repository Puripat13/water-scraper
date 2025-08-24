import os
import re
import time
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

# ---------------- CONFIG ----------------
URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = "waterlevel_report.csv"
DRIVE_FOLDER_ID = "your_drive_folder_id_here"   # <<== ใส่ folder id ของ Google Drive
ENABLE_GOOGLE_DRIVE_UPLOAD = True
# -----------------------------------------

def extract_thai(text: str) -> str:
    """ดึงเฉพาะตัวอักษรภาษาไทยจาก string"""
    if not isinstance(text, str):
        return ""
    match = re.findall(r"[ก-๙\s]+", text)
    return "".join(match).strip() if match else text

def init_drive():
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()  # เปิด browser ให้ login
    return GoogleDrive(gauth)

def drive_upload_or_update_csv(local_path, drive_folder_id, target_name):
    drive = init_drive()
    file_list = drive.ListFile({
        "q": f"'{drive_folder_id}' in parents and trashed=false"
    }).GetList()

    # หาไฟล์เก่าที่ชื่อเหมือนกัน
    file_id = None
    for f in file_list:
        if f["title"] == target_name:
            file_id = f["id"]
            break

    if file_id:
        file = drive.CreateFile({"id": file_id})
        file.SetContentFile(local_path)
        file.Upload()
        return "update", file_id
    else:
        file = drive.CreateFile({
            "title": target_name,
            "parents": [{"id": drive_folder_id}]
        })
        file.SetContentFile(local_path)
        file.Upload()
        return "upload", file["id"]

def scrape():
    print("[INFO] เปิดหน้า:", URL)
    driver = webdriver.Chrome()
    driver.get(URL)

    # รอ table โหลด
    WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table tbody tr"))
    )

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    print(f"[INFO] พบ {len(rows)} แถว")

    all_data = []
    for row in rows:
        cols = [c.text.strip() for c in row.find_elements(By.TAG_NAME, "td")]
        if cols:
            all_data.append(cols)

    driver.quit()
    return all_data

def save_and_upload(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก")
        return

    # ปรับความยาวให้เท่ากัน
    max_cols = max(len(r) for r in all_data)
    all_data = [r + [""] * (max_cols - len(r)) for r in all_data]

    # header ภาษาอังกฤษตามเว็บ
    headers = [
        "Station", "Location", "Time", "Water_Level",
        "Riverbank_Level", "Zero_Ref", "Capacity_Percent",
        "Status", "Collected_Date"
    ]
    if len(headers) < max_cols:
        headers += [f"Extra_{i+1}" for i in range(max_cols - len(headers))]

    file_exists = os.path.exists(CSV_OUT)
    df = pd.DataFrame(all_data, columns=headers)

    # ✅ clean ค่า Station ให้เหลือแค่ชื่อไทย
    df["Station"] = df["Station"].apply(extract_thai)

    # ✅ เพิ่มวันที่เก็บ
    df["Collected_Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # append ลงไฟล์
    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

    if ENABLE_GOOGLE_DRIVE_UPLOAD:
        try:
            action, file_id = drive_upload_or_update_csv(
                local_path=CSV_OUT,
                drive_folder_id=DRIVE_FOLDER_ID,
                target_name=os.path.basename(CSV_OUT)
            )
            print("☁️ Upload:", "อัปเดตไฟล์เดิม" if action == "update" else "อัปโหลดไฟล์ใหม่", f"(id={file_id})")
        except Exception as e:
            print("⚠️ อัปโหลดไปยัง Google Drive ล้มเหลว:", e)

if __name__ == "__main__":
    data = scrape()
    save_and_upload(data)
