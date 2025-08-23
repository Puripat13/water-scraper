# -*- coding: utf-8 -*-
"""
Scrape: https://nationalthaiwater.onwr.go.th/waterlevel
Append -> waterlevel_report.csv (utf-8-sig)
NOTE: ไม่มีส่วนอัปโหลด Drive (ให้ workflow ทำ)
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
from selenium.common.exceptions import TimeoutException, WebDriverException

# ================== CONFIG ==================
URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = os.environ.get("CSV_OUT", "waterlevel_report.csv")  # allow override from workflow
PAGELOAD_TIMEOUT = int(os.environ.get("PAGELOAD_TIMEOUT", "120"))
WAIT_SEC = float(os.environ.get("WAIT_SEC", "1.2"))
FIRST_WAIT = int(os.environ.get("FIRST_WAIT", "60"))  # wait for first table load
# ===================================================


def make_driver():
    opt = Options()
    # เหมาะกับ GitHub Actions / headless server
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

    drv = webdriver.Chrome(options=opt)  # Selenium Manager จะหาไดรเวอร์ให้เอง
    drv.set_page_load_timeout(PAGELOAD_TIMEOUT)
    drv.set_script_timeout(PAGELOAD_TIMEOUT)
    return drv


def _safe_navigate(driver, url: str):
    """หลีกเลี่ยง renderer timeout: ใช้ CDP navigate + fallback"""
    try:
        # เปิด Page domain ก่อน
        driver.execute_cdp_cmd("Page.enable", {})
        driver.execute_cdp_cmd("Page.navigate", {"url": url})
    except Exception:
        # fallback
        driver.get(url)


def scrape_waterlevel():
    driver = make_driver()
    start_time = time.time()
    try:
        # เปิดเว็บแบบไม่รอ render หนัก ๆ
        _safe_navigate(driver, URL)

        # รอให้มีแถวในตารางหน้าแรก (สูงสุด FIRST_WAIT วินาที)
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
                # บางวันคอลัมน์ท้ายเป็นวันที่อยู่แล้ว → บังคับให้มี "วันที่เก็บข้อมูล"
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

            # หาและคลิกปุ่ม next
            try:
                next_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button"))
                )
            except TimeoutException:
                break  # ไม่มีปุ่ม → หน้าสุดท้าย

            # ถ้า disabled ก็จบ
            try:
                disabled = next_btn.get_attribute("disabled")
                if disabled in ("true", True, "disabled"):
                    break
            except Exception:
                pass

            # คลิกด้วย JS ให้ชัวร์ (กัน overlay/obstruction)
            try:
                driver.execute_script("arguments[0].click();", next_btn)
                print("➡️ Next Page")
            except WebDriverException:
                # ลอง scroll แล้วคลิกอีกครั้ง
                driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", next_btn)

            # รอให้ page เปลี่ยน (จำนวนแถวเปลี่ยน)
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
            )

        return all_data, start_time

    except TimeoutException as e:
        # log แล้วโยนต่อ เพื่อให้ workflow fail (เห็นเหตุผลชัด)
        print(f"⚠️ Timeout while loading or waiting elements: {e}")
        raise
    finally:
        driver.quit()


# ----- helper: ตัดส่วนหน้าที่ไม่ใช่ไทยออก ให้เหลือชื่อสถานีภาษาไทย -----
def extract_thai(text: str) -> str:
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else ""


def save_csv(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก (all_data ว่าง) — จะไม่เขียนไฟล์")
        return 0

    # ทำความยาวแต่ละแถวให้เท่ากัน
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

    # ทำความสะอาดชื่อสถานี → เหลือเฉพาะภาษาไทย
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT} (append={'yes' if file_exists else 'no'})")
    return len(df)


def main():
    all_data, t0 = scrape_waterlevel()
    n = save_csv(all_data)
    elapsed = time.time() - t0
    print(f"⏱ ใช้เวลาในการรันทั้งหมด: {elapsed:.2f} วินาที, rows={n}")


if __name__ == "__main__":
    main()
