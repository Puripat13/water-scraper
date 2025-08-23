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
from selenium.common.exceptions import TimeoutException

# ================== CONFIG ==================
URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = "waterlevel_report.csv"
# ===================================================

# ================== Scraper ==================
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
    # เร็วขึ้น: ไม่รอโหลดทุก resource
    opt.page_load_strategy = "none"
    # บล็อก resource หนัก
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

    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(30)
    drv.set_script_timeout(30)
    return drv

def scrape_waterlevel():
    driver = make_driver()
    t0 = time.time()
    try:
        driver.get(URL)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
        )

        all_data = []
        current_date = datetime.today().strftime("%d/%m/%Y")

        while True:
            # เก็บข้อมูลในหน้านี้
            rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
            prev_first = rows[0].text if rows else ""

            for row in rows:
                cols = [c.text.strip() for c in row.find_elements(By.CSS_SELECTOR, "td")]
                if len(cols) < 5:
                    continue
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

            # หาและคลิกปุ่ม Next
            next_btns = driver.find_elements(By.XPATH, "//span[@title='Next Page']/button")
            if not next_btns or not next_btns[0].is_enabled():
                break

            driver.execute_script("arguments[0].click();", next_btns[0])

            # รอให้ตารางเปลี่ยนหน้า (หัวแถวแรกเปลี่ยน) สูงสุด ~10 วิ
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: (
                        d.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
                        and d.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")[0].text != prev_first
                    )
                )
            except TimeoutException:
                # ถ้าไม่เปลี่ยน ถือว่าจบ
                break

        return all_data, t0
    finally:
        try:
            driver.quit()
        except Exception:
            pass

# ----- helper: เก็บเฉพาะชื่อภาษาไทย (ตัดรหัส/เลข/อังกฤษก่อนหน้า) -----
def extract_thai(text: str) -> str:
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else ""

def save_csv(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก")
        return

    # ทำให้จำนวนคอลัมน์เท่ากัน
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

    # ชื่อสถานีเอาเฉพาะภาษาไทย
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    # แนะนำให้ลบแถวซ้ำเบื้องต้น (กันซ้ำข้ามรอบรัน)
    dedupe_keys = [k for k in ["ชื่อสถานี", "เวลา", "วันที่เก็บข้อมูล"] if k in df.columns]
    if dedupe_keys:
        df.drop_duplicates(subset=dedupe_keys, keep="last", inplace=True)

    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

def main():
    all_data, t0 = scrape_waterlevel()
    save_csv(all_data)
    print(f"⏱ ใช้เวลาในการรันทั้งหมด: {time.time() - t0:.2f} วินาที")

if __name__ == "__main__":
    main()
