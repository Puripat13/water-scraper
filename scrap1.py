# tmd_forecast_today_all.py
# -*- coding: utf-8 -*-

import os, time, random, base64, json
from datetime import datetime
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

HOME = os.getenv("TMD_HOME", "https://www.tmd.go.th")
CSV_OUT = os.getenv("CSV_OUT", "tmd_7day_forecast_today.csv")

# ====== (เดิม) อัปโหลด Drive เปิด/ปิดด้วย ENV ======
ENABLE_GOOGLE_DRIVE_UPLOAD = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "true").lower() == "true"
GDRIVE_SA_JSON = os.getenv("GDRIVE_SA_JSON", "")
GDRIVE_SA_JSON_BASE64 = os.getenv("GDRIVE_SA_JSON_BASE64", "")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
CSV_MIMETYPE = "text/csv"

def _ensure_service_account_file():
    try:
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            return True
        content = None
        if GDRIVE_SA_JSON_BASE64:
            content = base64.b64decode(GDRIVE_SA_JSON_BASE64).decode("utf-8")
        elif GDRIVE_SA_JSON:
            content = GDRIVE_SA_JSON
        if content:
            json.loads(content)  # validate
            with open(SERVICE_ACCOUNT_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        return False
    except Exception:
        return False

# ============ Driver: เบา/เร็ว ============
def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--disable-infobars")
    opt.add_argument("--window-size=1366,768")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--remote-allow-origins=*")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    # ไม่รอโหลดทั้งเพจ
    opt.page_load_strategy = "none"
    # บล็อค resource หนัก
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.fonts": 2,
        "profile.managed_default_content_settings.plugins": 2,
        "profile.managed_default_content_settings.popups": 2,
        "profile.managed_default_content_settings.notifications": 2,
        "profile.managed_default_content_settings.autoplay": 2,
    }
    opt.add_experimental_option("prefs", prefs)

    drv = webdriver.Chrome(options=opt)  # Selenium Manager ช่วยจัดการไดรเวอร์
    drv.set_page_load_timeout(18)
    drv.set_script_timeout(18)
    return drv

def safe_get(driver, url, timeout=18):
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
    except TimeoutException:
        try: driver.execute_script("window.stop();")
        except Exception: pass

def js_click(driver, el): driver.execute_script("arguments[0].click();", el)

def click_if_present(driver, by, selector, timeout=5):
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))
        js_click(driver, el); return True
    except: return False

# ============ Entry / Cookie ============
def bypass_eventday_cookie(driver):
    for xp in ["//button[contains(text(),'เข้าสู่เว็บไซต์')]", "//a[contains(text(),'เข้าสู่เว็บไซต์')]"]:
        if click_if_present(driver, By.XPATH, xp, 4): break
    for xp in ["//button[contains(text(),'ยอมรับทั้งหมด')]", "//button[contains(text(),'ยอมรับ')]"]:
        if click_if_present(driver, By.XPATH, xp, 3): break

def open_home_ready(driver):
    for _ in range(3):
        safe_get(driver, HOME, timeout=12)
        bypass_eventday_cookie(driver)
        try:
            WebDriverWait(driver, 18).until(
                EC.presence_of_element_located((By.ID, "select2-province-selector-container"))
            )
            return True
        except TimeoutException:
            try:
                driver.execute_script("window.stop();"); driver.refresh()
            except Exception: pass
    # dump ไว้ debug
    try:
        with open("debug_tmd_home.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot("debug_tmd_home.png")
    except Exception: pass
    raise TimeoutError("ไม่พบ select2 จังหวัดบนหน้าแรก TMD")

# ============ Select2: เร็วด้วย JS + mapping ครั้งเดียว ============
def _collect_select2_mapping_fast(driver):
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "select2-province-selector-container"))
    ).click()
    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input.select2-search__field"))
    )
    results = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "select2-province-selector-results"))
    )

    stable, last_cnt = 0, -1
    while True:
        items = results.find_elements(By.CSS_SELECTOR, "li.select2-results__option")
        cnt = len(items)
        if cnt == last_cnt:
            stable += 1
            if stable >= 2: break
        else:
            stable, last_cnt = 0, cnt
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", results)
        time.sleep(0.12)

    mapping = {}
    for li in items:
        name = (li.text or "").strip()
        if not name: continue
        li_id = li.get_attribute("id") or ""
        value = li_id.split("-")[-1] if "-" in li_id else name
        mapping[name] = value

    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    return mapping

def _js_set_select2_value(driver, value):
    js = """
    var sel = document.getElementById('province-selector');
    if (!sel) return false;
    sel.value = arguments[0];
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
    """
    try: return bool(driver.execute_script(js, value))
    except Exception: return False

def select_province_fast(driver, name, mapping):
    value = mapping.get(name)
    if value and _js_set_select2_value(driver, value):
        time.sleep(0.08)  # ให้ DOM อัปเดต
        return True
    # fallback: ค้นหา + คลิก
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "select2-province-selector-container"))
    ).click()
    search = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input.select2-search__field"))
    )
    search.clear(); search.send_keys(name)
    xp = ("//li[contains(@class,'select2-results__option') and normalize-space(text())='{0}']").format(name)
    WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, xp)))
    js_click(driver, driver.find_element(By.XPATH, xp))
    time.sleep(0.06)
    return True

# ============ Parse "วันนี้" แบบเร็ว (ไม่ใช้ bs4) ============
def parse_today_fast(driver, province_name):
    cards = driver.find_elements(By.CSS_SELECTOR, "div.card.card-shadow.text-center")
    for c in cards:
        try:
            head = c.find_element(By.CSS_SELECTOR, "div.font-small")
            if head.text.strip() != "วันนี้": continue
            date_txt = c.find_element(By.CSS_SELECTOR, "div.font-tiny.text-dark2").text.strip()
            # อุณหภูมิ สูง/ต่ำ
            twrap = c.find_element(By.CSS_SELECTOR, "div.d-flex.justify-content-around.sub-heading")
            dvals = twrap.find_elements(By.CSS_SELECTOR, "div")
            tmax = dvals[0].text.strip() if len(dvals) > 0 else ""
            tmin = dvals[2].text.strip() if len(dvals) > 2 else ""
            tinys = c.find_elements(By.CSS_SELECTOR, "div.font-tiny.text-center")
            cond  = tinys[0].text.strip() if len(tinys) > 0 else ""
            rain  = tinys[1].text.strip() if len(tinys) > 1 else ""
            wind = ""
            try: wind = c.find_element(By.CSS_SELECTOR, "span.font-tiny.ps-1").text.strip()
            except Exception: pass
            return {
                "จังหวัด/รายการ": province_name,
                "วันที่": date_txt,
                "อุณหภูมิสูงสุด": tmax,
                "อุณหภูมิต่ำสุด": tmin,
                "สภาพอากาศ": cond,
                "โอกาสฝน": rain,
                "ลม": wind,
                "เวลาบันทึก": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception:
            continue
    return None

# ============ (เดิม) ฟังก์ชัน Google Drive ============
def _build_drive_service_with_service_account():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/drive"]
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"ไม่พบไฟล์ service account: {SERVICE_ACCOUNT_FILE}")
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def drive_find_file_in_folder(service, filename, folder_id):
    fname = filename.replace("'", "\\'")
    q = f"name = '{fname}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    return res.get("files", [])

def drive_upload_or_update_csv(local_path, drive_folder_id, target_name=None, max_retries=3):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    if target_name is None: target_name = os.path.basename(local_path)
    service = _build_drive_service_with_service_account()
    try:
        service.files().get(fileId=drive_folder_id, fields="id, name, mimeType").execute()
    except HttpError as e:
        raise RuntimeError("เข้าถึงโฟลเดอร์ใน Drive ไม่ได้: ตรวจสอบการแชร์สิทธิ์") from e
    media = MediaFileUpload(local_path, mimetype=CSV_MIMETYPE, resumable=True)
    exists = drive_find_file_in_folder(service, target_name, drive_folder_id)
    for attempt in range(1, max_retries + 1):
        try:
            if exists:
                file_id = exists[0]["id"]
                updated = service.files().update(fileId=file_id, media_body=media).execute()
                return ("update", updated.get("id"))
            else:
                file_metadata = {"name": target_name, "parents": [drive_folder_id]}
                created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
                return ("create", created.get("id"))
        except HttpError:
            if attempt >= max_retries: raise
            time.sleep(2 * attempt)

# ============ Main ============
def main():
    had_sa = _ensure_service_account_file()

    driver = make_driver()
    rows, failed = [], []
    try:
        open_home_ready(driver)

        # สร้าง mapping จังหวัดครั้งเดียว แล้วใช้ JS set value (เร็ว)
        mapping = _collect_select2_mapping_fast(driver)
        names = list(mapping.keys())
        print(f"รายการจาก select2 ทั้งหมด: {len(names)} รายการ")

        for i, name in enumerate(names, 1):
            ok = False
            for attempt in range(2):
                try:
                    select_province_fast(driver, name, mapping)

                    # รอ card ปรากฏ/อัปเดตแบบสั้น ๆ
                    WebDriverWait(driver, 8).until(
                        EC.presence_of_all_elements_located(
                            (By.CSS_SELECTOR, "div.card.card-shadow.text-center")
                        )
                    )

                    row = parse_today_fast(driver, name)
                    if row:
                        rows.append(row); ok = True
                        if i % 10 == 0 or i <= 5:
                            print(f"[{i}/{len(names)}] {name} ✔")
                        break
                except Exception as e:
                    if attempt == 0:
                        try: driver.execute_script("window.stop();"); driver.refresh()
                        except Exception: pass
                    else:
                        print(f"[{i}/{len(names)}] {name} ✖ {e}")
            if not ok:
                failed.append(name)
    finally:
        try: driver.quit()
        except Exception: pass

    if rows:
        df = pd.DataFrame(rows)
        keep_cols = ["จังหวัด/รายการ", "สภาพอากาศ", "โอกาสฝน", "เวลาบันทึก"]
        df = df[keep_cols].rename(columns={
            "จังหวัด/รายการ": "Province",
            "สภาพอากาศ": "Weather",
            "โอกาสฝน": "RainChance",
            "เวลาบันทึก": "DateTime"
        })
        df["RainChance"] = (
            df["RainChance"].astype(str)
            .str.extract(r'(\d+)')[0]
            .astype(float)
            .div(100)
        )

        file_exists = os.path.exists(CSV_OUT)
        df.to_csv(CSV_OUT, mode="a", header=not file_exists, index=False, encoding="utf-8-sig")
        print(f"\n✅ บันทึก {len(df)} แถว ต่อท้ายไฟล์: {CSV_OUT}")

        # อัปโหลด Drive (ถ้าเปิดใช้ + มี SA + มีโฟลเดอร์)
        if ENABLE_GOOGLE_DRIVE_UPLOAD and DRIVE_FOLDER_ID and had_sa:
            try:
                action, file_id = drive_upload_or_update_csv(
                    local_path=CSV_OUT,
                    drive_folder_id=DRIVE_FOLDER_ID,
                    target_name=os.path.basename(CSV_OUT)
                )
                verb = "อัปเดตไฟล์" if action == "update" else "อัปโหลดไฟล์ใหม่"
                print(f"✅ {verb} ไปยัง Google Drive เรียบร้อย (fileId={file_id})")
            except Exception as e:
                print(f"⚠️ อัปโหลดไปยัง Google Drive ล้มเหลว: {e}")
        else:
            if not ENABLE_GOOGLE_DRIVE_UPLOAD:
                print("ℹ️ ข้ามการอัปโหลดไป Google Drive (ENABLE_GOOGLE_DRIVE_UPLOAD=false)")
            elif not had_sa:
                print("ℹ️ ไม่พบ Service Account ใน ENV: จะส่งออกเป็น workflow artifact แทน")
            elif not DRIVE_FOLDER_ID:
                print("ℹ️ ไม่มี DRIVE_FOLDER_ID: จะส่งออกเป็น workflow artifact แทน")

    if failed:
        print("\nรายการที่ดึงไม่สำเร็จ:", ", ".join(failed))

if __name__ == "__main__":
    main()
