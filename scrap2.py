# -*- coding: utf-8 -*-
"""
Scrape: https://nationalthaiwater.onwr.go.th/waterlevel
Append -> waterlevel_report.csv (utf-8-sig)
NOTE: ไม่มีส่วนอัปโหลด Drive (ให้ workflow ทำ)
"""
import os, time, re
from datetime import datetime
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ================== CONFIG ==================
URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = os.environ.get("CSV_OUT", "waterlevel_report.csv")
PAGELOAD_TIMEOUT = int(os.environ.get("PAGELOAD_TIMEOUT", "180"))
FIRST_WAIT = int(os.environ.get("FIRST_WAIT", "90"))    # wait table on first page
WAIT_SEC = float(os.environ.get("WAIT_SEC", "1.2"))      # small delay between pages
NAV_RETRIES = int(os.environ.get("NAV_RETRIES", "3"))    # navigate retry
# ===================================================

def _make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1920,1080")
    opt.add_argument("--disable-software-rasterizer")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--disable-features=Translate,BackForwardCache,MediaRouter")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--remote-allow-origins=*")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    # สำคัญ: อย่าให้ WebDriver รอ "โหลดครบทั้งหน้า"
    opt.set_capability("pageLoadStrategy", "none")
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(PAGELOAD_TIMEOUT)
    drv.set_script_timeout(PAGELOAD_TIMEOUT)
    return drv

def _navigate_with_retry(driver, url):
    last_err = None
    for i in range(1, NAV_RETRIES + 1):
        try:
            driver.get(url)              # ไม่รอโหลดเต็มเพราะเราใช้ pageLoadStrategy=none
            return
        except Exception as e:
            last_err = e
            print(f"⚠️ navigate attempt {i}/{NAV_RETRIES} failed: {e}")
            time.sleep(2 * i)
    raise last_err

def scrape_waterlevel():
    start_time = time.time()

    # สร้างไดรเวอร์ครั้งที่ 1
    driver = _make_driver()
    try:
        try:
            _navigate_with_retry(driver, URL)
        except Exception as nav_e:
            # fallback: รีสตาร์ทไดรเวอร์ 1 ครั้ง (กันเคส DevTools ค้าง)
            print("🔁 Restarting Chrome due to navigation errors…")
            try:
                driver.quit()
            except Exception:
                pass
            driver = _make_driver()
            _navigate_with_retry(driver, URL)

        # รอให้ตารางแรกโผล่ (แค่มีแถวก็พอ)
        WebDriverWait(driver, FIRST_WAIT).until(
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
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

            # ปุ่ม next
            try:
                next_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button"))
                )
            except TimeoutException:
                break  # ไม่มีปุ่ม/สุดหน้า

            # ถ้า disabled ก็เลิก
            try:
                if next_btn.get_attribute("disabled") in ("true", True, "disabled"):
                    break
            except Exception:
                pass

            # คลิกด้วย JS
            try:
                driver.execute_script("arguments[0].click();", next_btn)
                print("➡️ Next Page")
            except WebDriverException:
                driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", next_btn)

            # รอให้มีแถว (หน้าใหม่) แสดงผล
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
            )

        return all_data, start_time

    finally:
        try:
            driver.quit()
        except Exception:
            pass

# ----- helper -----
def extract_thai(text: str) -> str:
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else ""

def save_csv(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก — ข้ามการเขียนไฟล์")
        return 0

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
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT} (append={'yes' if file_exists else 'no'})")
    return len(df)

def main():
    all_data, t0 = scrape_waterlevel()
    n = save_csv(all_data)
    print(f"⏱ ใช้เวลา: {time.time()-t0:.2f}s, rows={n}")

if __name__ == "__main__":
    main()
