# -*- coding: utf-8 -*-
import os, time, re
from datetime import datetime
import pandas as pd

# -------- Selenium --------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# -------- Google Drive API (Service Account) --------
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ================== CONFIG ==================
URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = "waterlevel_report.csv"

# ----- Google Drive -----
ENABLE_GOOGLE_DRIVE_UPLOAD = True
SERVICE_ACCOUNT_FILE = "githubproject-467507-653192ee67bf.json"   # ไฟล์คีย์ SA
DRIVE_FOLDER_ID = "1UIrlesL0FcXIoZQdHbkI3PENe_M-JBlD"             # โฟลเดอร์ (My Drive หรือ Shared Drive ก็ได้)
CSV_MIMETYPE = "text/csv"
# ===================================================

# ================== Google Drive (TMD-style) ==================
def _check_prereq():
    if ENABLE_GOOGLE_DRIVE_UPLOAD:
        if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
            raise FileNotFoundError(f"ไม่พบไฟล์ Service Account: {SERVICE_ACCOUNT_FILE}")
        if not DRIVE_FOLDER_ID:
            raise ValueError("ยังไม่ได้ตั้ง DRIVE_FOLDER_ID")

def build_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def drive_find_file_in_folder(service, filename, folder_id):
    fname = filename.replace("'", "\\'")
    q = f"name = '{fname}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(
        q=q, fields="files(id,name)", includeItemsFromAllDrives=True, supportsAllDrives=True
    ).execute()
    return res.get("files", [])

def drive_upload_or_update_csv(local_path, drive_folder_id, target_name=None, max_retries=3):
    _check_prereq()
    service = build_drive_service()
    if target_name is None:
        target_name = os.path.basename(local_path)

    # เช็กว่า folderId ใช้ได้ (ไม่เช็กว่าเป็น Shared Drive)
    try:
        service.files().get(fileId=drive_folder_id, fields="id,name,mimeType", supportsAllDrives=True).execute()
    except HttpError as e:
        raise RuntimeError("เข้าถึงโฟลเดอร์ใน Drive ไม่ได้: ตรวจสอบว่าเชิญ Service Account เป็น Editor แล้ว") from e

    media = MediaFileUpload(local_path, mimetype=CSV_MIMETYPE, resumable=True)
    exists = drive_find_file_in_folder(service, target_name, drive_folder_id)

    for attempt in range(1, max_retries + 1):
        try:
            if exists:
                file_id = exists[0]["id"]
                updated = service.files().update(
                    fileId=file_id, media_body=media, supportsAllDrives=True
                ).execute()
                print(f"✅ อัปเดตไฟล์เดิมสำเร็จ (id={updated.get('id')})")
                return ("update", updated.get("id"))
            else:
                file_metadata = {"name": target_name, "parents": [drive_folder_id]}
                created = service.files().create(
                    body=file_metadata, media_body=media, fields="id,webViewLink", supportsAllDrives=True
                ).execute()
                print(f"✅ อัปโหลดไฟล์ใหม่สำเร็จ (id={created.get('id')})")
                if created.get("webViewLink"):
                    print(f"🔗 เปิดดูไฟล์: {created['webViewLink']}")
                return ("create", created.get("id"))
        except HttpError as e:
            print(f"❌ อัปโหลดล้มเหลว (attempt {attempt}/{max_retries}): {e}")
            if attempt >= max_retries:
                raise
            time.sleep(2 * attempt)

# ================== Scraper ==================
def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(60)
    return drv

def scrape_waterlevel():
    driver = make_driver()
    start_time = time.time()
    try:
        driver.get(URL)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
        )

        all_data = []
        current_date = datetime.today().strftime("%d/%m/%Y")

        while True:
            time.sleep(1.2)
            rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
            for row in rows:
                cols = [c.text.strip() for c in row.find_elements(By.CSS_SELECTOR, "td")]
                if len(cols) < 5:
                    continue
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

            try:
                next_btn = WebDriverWait(driver, 6).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button"))
                )
                if next_btn.is_enabled():
                    driver.execute_script("arguments[0].click();", next_btn)
                    print("➡️ Next Page")
                    time.sleep(1.0)
                else:
                    break
            except Exception:
                break

        return all_data, start_time
    finally:
        driver.quit()

# ----- helper: เก็บเฉพาะชื่อภาษาไทย (ตัดรหัส/เลข/อังกฤษก่อนหน้า) -----
def extract_thai(text: str) -> str:
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else ""

def save_and_upload(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก")
        return

    max_cols = max(len(r) for r in all_data)
    all_data = [r + [''] * (max_cols - len(r)) for r in all_data]

    headers = [
        "ชื่อสถานี", "ที่ตั้ง", "เวลา", "ระดับน้ำ",
        "ระดับตลิ่ง", "ค่าศูนย์เสาระดับ", "%ความจุน้ำ",
        "สถานการณ์", "วันที่เก็บข้อมูล"
    ]
    if len(headers) < max_cols:
        headers += [f"เพิ่มเติม_{i+1}" for i in range(max_cols - len(headers))]

    file_exists = os.path.exists(CSV_OUT)
    df = pd.DataFrame(all_data, columns=headers)

    # >>> เขียนทับคอลัมน์ 'ชื่อสถานี' ให้เหลือเฉพาะภาษาไทย (และตัวเลขที่อยู่หลังภาษาไทย) <<<
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

    if ENABLE_GOOGLE_DRIVE_UPLOAD:
        try:
            action, file_id = drive_upload_or_update_csv(
                local_path=CSV_OUT,
                drive_folder_id=DRIVE_FOLDER_ID,
                target_name=os.path.basename(CSV_OUT)
            )
            print("ผลการอัปโหลด:", "อัปเดตไฟล์เดิม" if action=="update" else "อัปโหลดไฟล์ใหม่", f"(id={file_id})")
        except Exception as e:
            print("⚠️ อัปโหลดไปยัง Google Drive ล้มเหลว:", e)

def main():
    all_data, t0 = scrape_waterlevel()
    save_and_upload(all_data)
    print(f"⏱ ใช้เวลาในการรันทั้งหมด: {time.time() - t0:.2f} วินาที")

if __name__ == "__main__":
    main()
