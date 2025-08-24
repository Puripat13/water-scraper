# -*- coding: utf-8 -*-
import os, time, re, sys, math
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
SCRAPE_BUDGET_SEC = int(os.environ.get("SCRAPE_BUDGET_SEC", "600"))  # ~10 นาที

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

def find_rich_table_locator(driver):
    cands = [
        (By.CSS_SELECTOR, "div.MuiDataGrid-virtualScrollerRenderZone .MuiDataGrid-row"),
        (By.CSS_SELECTOR, "div[role='rowgroup'] [role='row']"),
        (By.CSS_SELECTOR, ".MuiTable-root tbody tr"),
        (By.CSS_SELECTOR, "table tbody tr"),
    ]
    best, best_n = None, -1
    for by, sel in cands:
        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((by, sel)))
            n = len(driver.find_elements(by, sel))
            if n > best_n:
                best, best_n = (by, sel), n
        except Exception:
            pass
    if not best:
        raise TimeoutException("ไม่พบตารางข้อมูลบนหน้า")
    print(f"[INFO] ใช้ locator: {best} (เริ่ม {best_n} แถว)")
    return best

def find_paginator_root(driver):
    for sel in [".MuiTablePagination-root", "div.MuiDataGrid-footerContainer", "div[class*='MuiTablePagination']"]:
        for e in driver.find_elements(By.CSS_SELECTOR, sel):
            if e.is_displayed():
                return e
    return None

def set_rows_per_page_100(pager, driver):
    try:
        # ปุ่มเปิดเมนูขนาดหน้า
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

def get_display_text(pager, driver):
    # ข้อความเช่น "1–10 of 4921"
    sels = [
        ".MuiTablePagination-displayedRows",
        "*[class*='MuiTablePagination-displayedRows']",
    ]
    for sel in sels:
        es = pager.find_elements(By.CSS_SELECTOR, sel)
        for e in es:
            t = e.text.strip()
            if t:
                return t
    # สำรอง: มองทั่วหน้า
    try:
        es = driver.find_elements(By.XPATH, "//p[contains(.,' of ')]")
        for e in es:
            t = e.text.strip()
            if t:
                return t
    except Exception:
        pass
    return ""

def parse_total_from_display(txt):
    if not txt:
        return None, None, None
    nums = [int(x) for x in re.findall(r"\d+", txt)]
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]  # start, end, total
    if len(nums) == 1:
        return None, None, nums[0]
    return None, None, None

def find_next_in_pager(pager):
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

def extract_cells_from_row(r):
    tds = r.find_elements(By.CSS_SELECTOR, "td")
    if not tds:
        tds = r.find_elements(By.CSS_SELECTOR, "[role='gridcell']")
    return [c.text.strip() for c in tds if c.text is not None]

def get_rows(driver, locator):
    by, sel = locator
    rows = []
    for r in driver.find_elements(by, sel):
        cols = extract_cells_from_row(r)
        if cols:
            rows.append(cols)
    return rows

def extract_thai(s):
    if pd.isna(s) or s is None:
        return ""
    m = re.search(r"[ก-๙].*", str(s))
    return m.group(0).strip() if m else str(s).strip()

def save_csv(rows):
    if not rows:
        print("⚠️ ไม่พบข้อมูล")
        return
    headers = ["ชื่อสถานี","ที่ตั้ง","เวลา","ระดับน้ำ","ระดับตลิ่ง","ค่าศูนย์เสาระดับ","%ความจุน้ำ","สถานการณ์","วันที่เก็บข้อมูล"]
    fixed = []
    for r in rows:
        r = (list(r) + [""] * 9)[:9]
        fixed.append(r)
    df = pd.DataFrame(fixed, columns=headers)
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)
    df = df.replace({"-": "", "–": ""})
    file_exists = os.path.exists(CSV_OUT)
    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

def scrape_all():
    d = make_driver()
    t0 = time.time()
    try:
        print(f"[INFO] เปิดหน้า: {URL}")
        d.get(URL)
        WebDriverWait(d, 30).until(EC.presence_of_element_located((By.XPATH, "//*")))
        time.sleep(0.5)

        locator = find_rich_table_locator(d)
        pager = find_paginator_root(d)
        if pager:
            set_rows_per_page_100(pager, d)
            time.sleep(0.2)

        txt = get_display_text(pager, d) if pager else ""
        s, e, total_n = parse_total_from_display(txt)
        page_size = max(1, (e - s + 1) if (s and e) else 10)
        pages_plan = max(1, math.ceil(total_n / page_size)) if total_n else None
        if pages_plan:
            print(f"[INFO] paginator: '{txt}' -> total={total_n}, page_size={page_size}, pages={pages_plan}")

        all_rows = []
        curdate = datetime.today().strftime("%d/%m/%Y")
        page = 1

        while True:
            if time.time() - t0 > SCRAPE_BUDGET_SEC:
                print(f"[WARN] หมดงบเวลา {SCRAPE_BUDGET_SEC}s -> หยุด")
                break

            rows_elems = d.find_elements(*locator)
            first_old = rows_elems[0] if rows_elems else None

            # เก็บหน้า
            rows = get_rows(d, locator)
            for r in rows:
                r = (r + [""] * 9)[:9]
                r[-1] = curdate
                all_rows.append(r)

            # แสดงผลเป็นช่วงๆ เพื่อลด IO
            if page % 20 == 0:
                print(f"[INFO] Page {page}: สะสม {len(all_rows)} แถว")

            # ไปหน้าถัดไป
            if not pager:
                print("[INFO] ไม่พบ paginator -> จบ")
                break
            if pages_plan and page >= pages_plan:
                print(f"[INFO] ครบ {page}/{pages_plan} หน้า -> จบ")
                break

            nxt = find_next_in_pager(pager)
            if not nxt:
                print("[INFO] ไม่พบปุ่มถัดไป -> จบ")
                break

            try:
                d.execute_script("arguments[0].click();", nxt)
                # รอจนแถวเดิมโดน replace จริง (เร็วกว่า loop เช็ค signature)
                if first_old:
                    WebDriverWait(d, 10).until(EC.staleness_of(first_old))
                WebDriverWait(d, 10).until(lambda x: len(get_rows(x, locator)) > 0)
                page += 1
            except Exception as e:
                print(f"[WARN] ไปหน้าถัดไปไม่สำเร็จ: {e} -> จบ")
                break

        cleaned = [r for r in all_rows if re.search(r"[ก-๙]", r[0] if r else "")]
        return cleaned, t0
    finally:
        d.quit()

def main():
    try:
        rows, t0 = scrape_all()
        save_csv(rows)
        print(f"⏱ ใช้เวลา: {time.time() - t0:.2f}s, รวม {len(rows)} แถว")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
