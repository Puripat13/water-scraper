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

def make_driver():
    from selenium.webdriver import ChromeOptions
    opt = ChromeOptions()
    # --- เสถียรบน CI (headless) ---
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1920,1080")
    opt.add_argument("--disable-software-rasterizer")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--no-first-run")
    opt.add_argument("--no-default-browser-check")
    opt.add_argument("--proxy-server='direct://'")
    opt.add_argument("--proxy-bypass-list=*")
    opt.add_argument("--disable-features=NetworkServiceInProcess")
    # ลดการถูกจับว่าเป็นบอท
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    opt.add_experimental_option("useAutomationExtension", False)
    # ไม่รอ asset ยิบย่อย
    opt.set_capability("pageLoadStrategy", "eager")
    # user-agent ให้เหมือน desktop จริง
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    drv = webdriver.Chrome(options=opt)
    # ปลอม navigator.webdriver = undefined (กัน anti-bot เบื้องต้น)
    try:
        drv.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        })
    except Exception:
        pass

    drv.set_page_load_timeout(120)  # เดิม 60 -> 120
    drv.implicitly_wait(0)          # ใช้ explicit wait แทน
    return drv


def open_with_retry(driver, url, retries=2):
    for i in range(1, retries + 1):
        try:
            driver.get(url)
            # รอ DOM หลักขึ้น (ไม่ต้องครบทุก asset)
            WebDriverWait(driver, 30).until(
                lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            )
            return True
        except TimeoutException:
            print(f"⚠️ page load timeout #{i}; stop() แล้วไปต่อแบบรอ element")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            # ให้ไปต่อโดยรอ element เป้าหมาย
            return True
    return False


def scrape_waterlevel():
    driver = make_driver()
    start_time = time.time()
    try:
        ok = open_with_retry(driver, URL, retries=2)
        if not ok:
            raise RuntimeError("เปิดหน้าเว็บไม่สำเร็จหลัง retry")

        WebDriverWait(driver, 40).until(
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
                next_btn = WebDriverWait(driver, 8).until(
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

    # เขียนทับคอลัมน์ 'ชื่อสถานี' ให้เหลือเฉพาะภาษาไทย
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")


def main():
    all_data, t0 = scrape_waterlevel()
    save_csv(all_data)
    print(f"⏱ ใช้เวลาในการรันทั้งหมด: {time.time() - t0:.2f} วินาที")


if __name__ == "__main__":
    main()
