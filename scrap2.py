# -*- coding: utf-8 -*-
"""
Scrape: https://nationalthaiwater.onwr.go.th/waterlevel
Append -> waterlevel_report.csv (utf-8-sig)
NOTE: ไม่มีส่วนอัปโหลด Google Drive แล้ว (ให้ workflow ทำแทน)
"""
import os, time, re
from datetime import datetime
import pandas as pd

# -------- Selenium --------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================== CONFIG ==================
URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = os.environ.get("CSV_OUT", "waterlevel_report.csv")  # allow override from workflow
PAGELOAD_TIMEOUT = int(os.environ.get("PAGELOAD_TIMEOUT", "60"))
WAIT_SEC = float(os.environ.get("WAIT_SEC", "1.2"))
# ===================================================

def make_driver():
    opt = Options()
    # ใช้ headless แบบใหม่ (เหมาะกับ GitHub Actions)
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1920,1080")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    drv = webdriver.Chrome(options=opt)  # Selenium Manager จะจัดการไดรเวอร์ให้
    drv.set_page_load_timeout(PAGELOAD_TIMEOUT)
    return drv

def scrape_waterlevel():
    driver = make_driver()
    start_time = time.time()
    try:
        driver.get(URL)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
        )
        all_data = []
        current_date = datetime.today().strftime("%d/%m/%Y")

        while True:
            time.sleep(WAIT_SEC)
            rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
            for row in rows:
                cols = [c.text.strip() for c in row.find_elements(By.CSS_SELECTOR, "td")]
                if len(cols) < 5:
                    continue
                # หน้าเว็บบางวันมี 8–9 คอลัมน์ไม่เท่ากัน -> บังคับให้มีคอลัมน์ "วันที่เก็บข้อมูล"
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

            # ปุ่ม next
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

def save_csv(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก (all_data ว่าง) — จะไม่เขียนไฟล์")
        return 0

    # ทำ row ให้ความยาวเท่ากัน
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

    # ทำความสะอาดชื่อสถานี -> เหลือเฉพาะภาษาไทย
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    # เขียนหัวตารางเฉพาะครั้งแรกที่ไฟล์ยังไม่ถูกสร้าง
    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT} (append={'no' if not file_exists else 'yes'})")
    return len(df)

def main():
    all_data, t0 = scrape_waterlevel()
    n = save_csv(all_data)
    elapsed = time.time() - t0
    print(f"⏱ ใช้เวลาในการรันทั้งหมด: {elapsed:.2f} วินาที, rows={n}")

if __name__ == "__main__":
    main()
