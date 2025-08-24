# -*- coding: utf-8 -*-
import os, time, re, sys
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
CSV_OUT = "waterlevel_report.csv"
WAIT_SEC = 30
# ===================================================

def make_driver():
    opt = Options()
    # เร็วขึ้นสำหรับ CI
    opt.page_load_strategy = "eager"
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1366,768")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--disable-infobars")
    opt.add_argument("--disable-notifications")
    opt.add_argument("--lang=th-TH,th")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(60)
    return drv

def wait_rows(driver):
    """
    รอให้มีแถวข้อมูลโผล่ โดยพยายามทั้งรูปแบบ Table ปกติ และ DataGrid (role='row')
    """
    sel_try = [
        (By.CSS_SELECTOR, ".MuiTable-root tbody tr"),
        (By.CSS_SELECTOR, "table tbody tr"),
        (By.CSS_SELECTOR, "div[role='rowgroup'] [role='row']"),
    ]
    for by, sel in sel_try:
        try:
            WebDriverWait(driver, WAIT_SEC).until(EC.presence_of_element_located((by, sel)))
            rows = driver.find_elements(by, sel)
            if rows:
                return (by, sel)
        except Exception:
            pass
    raise TimeoutError("ไม่พบแถวข้อมูลในหน้า (ทั้ง Table และ DataGrid)")

def find_next_button(driver):
    """
    หาปุ่ม 'หน้าถัดไป' หลายรูปแบบที่พบบ่อยบนเว็บ MUI/DataGrid
    """
    xpaths = [
        "//button[@aria-label='Next page' and not(@disabled)]",
        "//span[@title='Next Page']/button[not(@disabled)]",
        # ปุ่มลูกศรขวา ที่ไม่ได้ disabled
        "//button[.//*[name()='svg' or name()='path']]"
        "[not(@disabled) and (contains(., 'Next') or @aria-label='Next page')]",
        # สำรอง: ปุ่มที่มี title/aria-label เป็น next
        "//*[self::button or self::span][contains(@title,'Next') or contains(@aria-label,'Next')]/self::button[not(@disabled)]",
    ]
    for xp in xpaths:
        els = driver.find_elements(By.XPATH, xp)
        for el in els:
            try:
                if el.is_enabled():
                    return el
            except Exception:
                continue
    # แบบ CSS (บางธีมใช้ไอคอน)
    css_try = [
        "button[aria-label='Next page']:not([disabled])",
        "span[title='Next Page'] > button:not([disabled])",
    ]
    for sel in css_try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els:
            try:
                if el.is_enabled():
                    return el
            except Exception:
                continue
    return None

def get_rows(driver, row_locator):
    by, sel = row_locator
    rows = driver.find_elements(by, sel)
    # กรณี DataGrid, บางแถวเป็น header role=row ให้กรอง td/cell
    out = []
    for row in rows:
        tds = row.find_elements(By.CSS_SELECTOR, "td")
        if not tds:
            # บาง DataGrid ใช้ role='gridcell'
            tds = row.find_elements(By.CSS_SELECTOR, "[role='gridcell']")
        cols = [c.text.strip() for c in tds]
        if cols:
            out.append(cols)
    # ถ้ายังไม่ได้อะไร ลองแบบ table ปกติซ้ำอีกรอบ
    if not out:
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        for row in rows:
            tds = row.find_elements(By.CSS_SELECTOR, "td")
            cols = [c.text.strip() for c in tds]
            if cols:
                out.append(cols)
    return out

# ----- helper: เก็บเฉพาะชื่อภาษาไทย (ตัดรหัส/เลข/อังกฤษก่อนหน้า) -----
def extract_thai(text: str) -> str:
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else str(text).strip()

def scrape_waterlevel():
    driver = make_driver()
    start_time = time.time()
    try:
        print(f"[INFO] เปิดหน้า: {URL}")
        driver.get(URL)

        print("[INFO] รอให้แถวข้อมูลโผล่…")
        row_locator = wait_rows(driver)
        print(f"[INFO] ใช้ locator: {row_locator}")

        all_data = []
        current_date = datetime.today().strftime("%d/%m/%Y")
        page_idx = 1

        while True:
            time.sleep(1.2)

            rows = get_rows(driver, row_locator)
            print(f"[INFO] Page {page_idx}: พบ {len(rows)} แถว")
            for r in rows:
                # กันคอลัมน์ไม่ครบ -> เติมให้ครบ 9 ช่อง
                while len(r) < 9:
                    r.append("")
                # ถ้ามากกว่า 9 ก็จะตัดทิ้งท้าย (กันเว็บเพิ่มคอลัมน์ใหม่แบบไม่คาดคิด)
                if len(r) > 9:
                    r = r[:9]
                # คอลัมน์สุดท้ายให้เป็นวันที่เก็บข้อมูล
                r[-1] = current_date
                all_data.append(r)

            # หาและคลิกปุ่มถัดไป
            try:
                next_btn = find_next_button(driver)
                if next_btn and next_btn.is_enabled():
                    driver.execute_script("arguments[0].click();", next_btn)
                    print("➡️ Next Page")
                    page_idx += 1
                    time.sleep(1.0)
                    # รอให้หน้าถัดไปมีแถวใหม่ (อย่างน้อย 1 แถว)
                    WebDriverWait(driver, 10).until(lambda d: len(get_rows(d, row_locator)) > 0)
                else:
                    print("[INFO] ไม่พบปุ่มถัดไป หรือปุ่มถูกปิดการใช้งาน -> จบการดึงข้อมูล")
                    break
            except Exception as e:
                print(f"[WARN] ไปหน้าถัดไปไม่สำเร็จ: {e} -> จบการดึงข้อมูล")
                break

        return all_data, start_time
    finally:
        driver.quit()

def save_csv(all_data):
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก")
        return

    # บังคับ 9 คอลัมน์ตามเฮดเดอร์
    headers = [
        "ชื่อสถานี", "ที่ตั้ง", "เวลา", "ระดับน้ำ",
        "ระดับตลิ่ง", "ค่าศูนย์เสาระดับ", "%ความจุน้ำ",
        "สถานการณ์", "วันที่เก็บข้อมูล"
    ]
    fixed = []
    for r in all_data:
        row = list(r)[:9]
        while len(row) < 9:
            row.append("")
        fixed.append(row)

    file_exists = os.path.exists(CSV_OUT)
    df = pd.DataFrame(fixed, columns=headers)

    # เขียนทับคอลัมน์ 'ชื่อสถานี' ให้เหลือเฉพาะภาษาไทย
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

def main():
    try:
        all_data, t0 = scrape_waterlevel()
        save_csv(all_data)
        print(f"⏱ ใช้เวลาในการรันทั้งหมด: {time.time() - t0:.2f} วินาที")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
