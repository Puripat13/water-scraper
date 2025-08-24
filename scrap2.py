# -*- coding: utf-8 -*-
import os, time, re, sys
from datetime import datetime
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

URL = "https://nationalthaiwater.onwr.go.th/waterlevel"
CSV_OUT = "waterlevel_report.csv"

# ---- สคีมาคงที่ (อังกฤษ 9 คอลัมน์) ----
HEADERS = [
    "Station", "Location", "Time", "Water_Level",
    "Bank_Level", "Gauge_Zero", "Capacity_Percent",
    "Status", "Data_Time"
]

# ================= Driver =================
def make_driver():
    opt = Options()
    opt.page_load_strategy = "eager"
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1366,840")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--lang=th-TH,th")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(60)
    return drv

# ================= Helpers =================
def find_table_locator(driver):
    cands = [
        (By.CSS_SELECTOR, "div.MuiDataGrid-virtualScrollerRenderZone .MuiDataGrid-row"),
        (By.CSS_SELECTOR, "div[role='rowgroup'] [role='row']"),
        (By.CSS_SELECTOR, ".MuiTable-root tbody tr"),
        (By.CSS_SELECTOR, "table tbody tr"),
    ]
    best, best_n = None, -1
    for by, sel in cands:
        try:
            WebDriverWait(driver, 6).until(EC.presence_of_element_located((by, sel)))
            n = len(driver.find_elements(by, sel))
            if n > best_n:
                best, best_n = (by, sel), n
        except Exception:
            pass
    if not best:
        raise TimeoutException("ไม่พบตารางข้อมูลบนหน้า")
    print(f"[INFO] ใช้ locator: {best} (เริ่ม {best_n} แถว)")
    return best

def paginator_root(driver):
    for sel in [".MuiTablePagination-root", "div.MuiDataGrid-footerContainer", "div[class*='MuiTablePagination']"]:
        for e in driver.find_elements(By.CSS_SELECTOR, sel):
            if e.is_displayed():
                return e
    return None

def set_rows_per_page_100(pager, driver):
    try:
        triggers = pager.find_elements(By.XPATH, ".//*[(@role='button' or contains(@class,'MuiSelect-select'))]")
        for t in triggers:
            try:
                driver.execute_script("arguments[0].click();", t)
                time.sleep(0.1)
                items = driver.find_elements(By.XPATH, "//li[normalize-space(.)='100']")
                if items:
                    driver.execute_script("arguments[0].click();", items[0])
                    print("[INFO] ตั้ง Rows/page = 100")
                    time.sleep(0.2)
                    return
            except Exception:
                continue
    except Exception:
        pass

def next_button_in(pager):
    xps = [
        ".//button[@aria-label='Next page' and not(@disabled)]",
        ".//span[@title='Next Page']/button[not(@disabled)]",
        ".//button[not(@disabled) and (contains(., 'Next') or contains(., 'ถัดไป'))]",
    ]
    for xp in xps:
        for el in pager.find_elements(By.XPATH, xp):
            if el.is_displayed() and el.is_enabled():
                return el
    return None

def cells_of_row(r):
    tds = r.find_elements(By.CSS_SELECTOR, "td") or r.find_elements(By.CSS_SELECTOR, "[role='gridcell']")
    return [c.text.strip() for c in tds]

def get_rows(driver, locator):
    by, sel = locator
    rows = []
    for r in driver.find_elements(by, sel):
        cols = cells_of_row(r)
        if cols:
            rows.append(cols)
    return rows

# ---- ตัดรหัส/ตัวเลข/ตัวอังกฤษหน้าชื่อสถานี ----
def clean_station(text: str) -> str:
    """เก็บเฉพาะตั้งแต่ 'อักษรไทยตัวแรก' ของชื่อสถานี"""
    if pd.isna(text) or text is None:
        return ""
    s = str(text).strip()
    m = re.search(r"[ก-๙].*", s)  # หาอักษรไทยตัวแรก
    return m.group(0).strip() if m else s  # ถ้าไม่เจอไทย ให้คืนค่าเดิม

# ================= Scrape =================
def scrape_all():
    d = make_driver()
    t0 = time.time()
    try:
        print(f"[INFO] เปิดหน้า: {URL}")
        d.get(URL)
        WebDriverWait(d, 30).until(EC.presence_of_element_located((By.XPATH, "//*")))
        time.sleep(0.5)

        locator = find_table_locator(d)
        pager = paginator_root(d)
        if pager:
            set_rows_per_page_100(pager, d)
            time.sleep(0.2)

        all_rows = []
        curdate = datetime.today().strftime("%d/%m/%Y")
        page = 1

        while True:
            rows_elems = d.find_elements(*locator)
            first_old = rows_elems[0] if rows_elems else None

            rows = get_rows(d, locator)
            for r in rows:
                r = (r + [""] * 9)[:9]  # บังคับ 9 ช่อง
                r[-1] = curdate        # ใส่ Data_Time
                all_rows.append(r)

            if not pager:
                print("[INFO] ไม่พบ paginator -> จบ")
                break

            nxt = next_button_in(pager)
            if not nxt:
                print("[INFO] ไม่พบปุ่มถัดไป -> จบ")
                break

            try:
                d.execute_script("arguments[0].click();", nxt)
                if first_old:
                    WebDriverWait(d, 10).until(EC.staleness_of(first_old))
                WebDriverWait(d, 10).until(lambda x: len(get_rows(x, locator)) > 0)
                page += 1
                if page % 20 == 0:
                    print(f"[INFO] Page {page}")
            except Exception as e:
                print(f"[WARN] ไปหน้าถัดไปไม่สำเร็จ: {e} -> จบ")
                break

        return all_rows, t0
    finally:
        d.quit()

# ================= Save =================
def save_csv(rows):
    if not rows:
        print("⚠️ ไม่พบข้อมูล")
        return

    fixed = []
    for r in rows:
        r = (list(r) + [""] * 9)[:9]
        fixed.append(r)
    df = pd.DataFrame(fixed, columns=HEADERS)

    # ตัดรหัสหน้า 'Station' และทำความสะอาดค่าเล็กน้อย
    df["Station"] = df["Station"].apply(clean_station)
    df = df.replace({"-": "", "–": ""})

    file_exists = os.path.exists(CSV_OUT)
    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

# ================= Main =================
def main():
    try:
        rows, t0 = scrape_all()
        # เก็บเฉพาะแถวที่มีอักษรจริงใน Station
        rows = [r for r in rows if re.search(r"[ก-๙A-Za-z]", r[0] if r else "")]
        save_csv(rows)
        print(f"⏱ ใช้เวลา: {time.time() - t0:.2f}s")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
