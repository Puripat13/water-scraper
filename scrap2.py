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
WAIT = 30

def make_driver():
    opt = Options()
    opt.page_load_strategy = "eager"
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1366,800")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--lang=th-TH,th")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(60)
    return drv

def pick_richest_table_locator(driver):
    """ลองทุก selector ที่เจอตาราง แล้วเลือกตัวที่จำนวนแถว 'มากที่สุด'"""
    candidates = [
        (By.CSS_SELECTOR, "div.MuiDataGrid-virtualScrollerRenderZone .MuiDataGrid-row"),
        (By.CSS_SELECTOR, "div[role='rowgroup'] [role='row']"),
        (By.CSS_SELECTOR, ".MuiTable-root tbody tr"),
        (By.CSS_SELECTOR, "table tbody tr"),
    ]
    best = None
    best_n = -1
    for by, sel in candidates:
        try:
            WebDriverWait(driver, 8).until(EC.presence_of_element_located((by, sel)))
        except TimeoutException:
            continue
        rows = driver.find_elements(by, sel)
        n = len(rows)
        if n > best_n:
            best_n = n
            best = (by, sel)
    if not best:
        raise TimeoutException("ไม่พบตารางข้อมูลบนหน้า")
    print(f"[INFO] ใช้ locator: {best} (แถวเริ่มต้น {best_n})")
    return best

def set_rows_per_page_100(driver):
    """พยายามตั้ง Rows per page = 100 (ถ้ามี)"""
    try:
        # MUI pagination select
        # หา select ที่มีค่า 10/25/50/100
        options_xpath = "//ul//li[normalize-space(.)='100']"
        # เปิดเมนู page size
        triggers = driver.find_elements(By.XPATH, "//div[contains(@class,'MuiTablePagination') or contains(@class,'MuiDataGrid')]//div[contains(@class,'MuiSelect-select') or @role='button']")
        for trg in triggers:
            try:
                driver.execute_script("arguments[0].click();", trg)
                time.sleep(0.3)
                items = driver.find_elements(By.XPATH, options_xpath)
                if items:
                    driver.execute_script("arguments[0].click();", items[0])
                    print("[INFO] ตั้ง Rows per page = 100")
                    time.sleep(0.6)
                    return
            except Exception:
                continue
    except Exception:
        pass

def find_next_btn(driver):
    xps = [
        "//button[@aria-label='Next page' and not(@disabled)]",
        "//span[@title='Next Page']/button[not(@disabled)]",
        "//button[not(@disabled) and (contains(., 'ถัดไป') or contains(., 'Next'))]",
        "//button[not(@disabled) and .//*[local-name()='svg' or local-name()='path']]",
    ]
    for xp in xps:
        els = driver.find_elements(By.XPATH, xp)
        for el in els:
            try:
                if el.is_enabled() and el.is_displayed():
                    return el
            except Exception:
                continue
    css = [
        "button[aria-label='Next page']:not([disabled])",
        "span[title='Next Page'] > button:not([disabled])",
    ]
    for sel in css:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els:
            try:
                if el.is_enabled() and el.is_displayed():
                    return el
            except Exception:
                continue
    return None

def extract_cells_from_row(row):
    tds = row.find_elements(By.CSS_SELECTOR, "td")
    if not tds:
        tds = row.find_elements(By.CSS_SELECTOR, "[role='gridcell']")
    return [c.text.strip() for c in tds if c.text is not None]

def get_rows(driver, locator):
    by, sel = locator
    rows_el = driver.find_elements(by, sel)
    rows = []
    for r in rows_el:
        cols = extract_cells_from_row(r)
        if cols:
            rows.append(cols)
    return rows

def extract_thai(text):
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else str(text).strip()

def scrape():
    d = make_driver()
    t0 = time.time()
    try:
        print(f"[INFO] เปิดหน้า: {URL}")
        d.get(URL)

        # รอจนมีเนื้อหาบางอย่างในหน้า
        WebDriverWait(d, WAIT).until(EC.presence_of_element_located((By.XPATH, "//*")))
        time.sleep(1.0)

        locator = pick_richest_table_locator(d)
        set_rows_per_page_100(d)

        all_rows = []
        curdate = datetime.today().strftime("%d/%m/%Y")
        page = 1

        while True:
            time.sleep(1.0)
            rows = get_rows(d, locator)
            print(f"[INFO] Page {page}: พบ {len(rows)} แถว")
            for r in rows:
                # บังคับ 9 คอลัมน์
                r = (r + [""] * 9)[:9]
                r[-1] = curdate  # วันที่เก็บข้อมูล
                all_rows.append(r)

            nxt = find_next_btn(d)
            if not nxt:
                print("[INFO] ไม่มีปุ่มถัดไป -> จบ")
                break
            try:
                d.execute_script("arguments[0].click();", nxt)
                page += 1
                WebDriverWait(d, 10).until(lambda x: len(get_rows(x, locator)) > 0)
            except Exception as e:
                print(f"[WARN] กดถัดไปไม่สำเร็จ: {e} -> จบ")
                break

        return all_rows, t0
    finally:
        d.quit()

def save_csv(rows):
    if not rows:
        print("⚠️ ไม่พบข้อมูล")
        return
    headers = [
        "ชื่อสถานี","ที่ตั้ง","เวลา","ระดับน้ำ",
        "ระดับตลิ่ง","ค่าศูนย์เสาระดับ","%ความจุน้ำ",
        "สถานการณ์","วันที่เก็บข้อมูล"
    ]
    fixed = []
    for r in rows:
        r = (list(r) + [""] * 9)[:9]
        fixed.append(r)
    df = pd.DataFrame(fixed, columns=headers)
    df["ชื่อสถานี"] = df["ชื่อสถานี"].apply(extract_thai)

    # กันเครื่องหมาย – หรือ '-' ให้เป็นค่าว่าง
    df = df.replace({"-": "", "–": ""})

    file_exists = os.path.exists(CSV_OUT)
    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

def main():
    try:
        rows, t0 = scrape()
        # เลือก keep เฉพาะแถวที่มีอักษรไทยในชื่อสถานี (กัน header แฝง)
        rows = [r for r in rows if re.search(r"[ก-๙]", r[0] if r else "")]
        save_csv(rows)
        print(f"⏱ ใช้เวลา: {time.time()-t0:.2f}s")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
