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

# งบเวลารวมของการ scrape (วินาที) - ตั้งจาก ENV ได้ เช่น 600 = 10 นาที
SCRAPE_BUDGET_SEC = int(os.environ.get("SCRAPE_BUDGET_SEC", "600"))

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

# ---------- Tools around the table/paginator ----------
def find_rich_table_locator(driver):
    """ลองหลาย selector แล้วเลือกตารางที่ 'มีแถวมากสุด' เพื่อเล็งถูกตัว"""
    cands = [
        (By.CSS_SELECTOR, "div.MuiDataGrid-virtualScrollerRenderZone .MuiDataGrid-row"),
        (By.CSS_SELECTOR, "div[role='rowgroup'] [role='row']"),
        (By.CSS_SELECTOR, ".MuiTable-root tbody tr"),
        (By.CSS_SELECTOR, "table tbody tr"),
    ]
    best = None
    best_n = -1
    for by, sel in cands:
        try:
            WebDriverWait(driver, 6).until(EC.presence_of_element_located((by, sel)))
            n = len(driver.find_elements(by, sel))
            if n > best_n:
                best_n = n
                best = (by, sel)
        except Exception:
            pass
    if not best:
        raise TimeoutException("ไม่พบตารางข้อมูลบนหน้า")
    print(f"[INFO] ใช้ locator: {best} (แถวเริ่มต้น {best_n})")
    return best

def find_paginator_root(driver):
    """หา paginator หลักของตาราง (โซนแสดง '1–100 of N' และปุ่ม next)"""
    sels = [
        ".MuiTablePagination-root",
        "div.MuiDataGrid-footerContainer",
        "div[class*='MuiTablePagination']",
    ]
    for sel in sels:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for e in els:
            if e.is_displayed():
                return e
    return None

def set_rows_per_page_100(pager):
    """พยายามตั้ง Rows per page = 100 ถ้าเมนูมีตัวเลือกนี้"""
    try:
        # ปุ่มเปิดเมนู page-size มักเป็น div[role=button] หรือ .MuiSelect-select
        triggers = pager.find_elements(By.XPATH, ".//*[(@role='button' or contains(@class,'MuiSelect-select'))]")
        for trg in triggers:
            try:
                trg.click()
                time.sleep(0.2)
                items = pager.find_elements(By.XPATH, "//li[normalize-space(.)='100']")
                if not items:
                    # เมนูอาจวางนอก pager (เป็น portal)
                    items = pager._parent.find_elements(By.XPATH, "//li[normalize-space(.)='100']")
                if items:
                    items[0].click()
                    print("[INFO] ตั้ง Rows/page = 100")
                    time.sleep(0.5)
                    return
            except Exception:
                continue
    except Exception:
        pass

def get_display_text(pager):
    """ดึงข้อความ '1–100 of N' (หรือรูปแบบใกล้เคียง)"""
    sels = [
        ".MuiTablePagination-displayedRows",
        "*[class*='MuiTablePagination-displayedRows']",
        "//p[contains(.,' of ')]",
    ]
    for sel in sels:
        try:
            if sel.startswith("//"):
                els = pager._parent.find_elements(By.XPATH, sel)
            else:
                els = pager.find_elements(By.CSS_SELECTOR, sel)
            for e in els:
                t = e.text.strip()
                if t:
                    return t
        except Exception:
            continue
    return ""

def parse_total_from_display(txt):
    """
    พยายามดึงตัวเลขรวม N จากข้อความอย่าง '1–100 of 1234'
    จะคืน (start, end, total) ถ้าจับได้, ไม่งั้นคืน (None, None, None)
    """
    if not txt:
        return None, None, None
    # แยกเลขทั้งหมด
    nums = [int(x) for x in re.findall(r"\d+", txt)]
    if len(nums) >= 3:
        # เดาสามตัวแรกเป็น start, end, total
        return nums[0], nums[1], nums[2]
    if len(nums) == 1:
        return None, None, nums[0]
    return None, None, None

def find_next_in_pager(pager):
    """หา next ภายใน pager เท่านั้น (กันกดผิด component)"""
    xps = [
        ".//button[@aria-label='Next page' and not(@disabled)]",
        ".//span[@title='Next Page']/button[not(@disabled)]",
        ".//button[not(@disabled) and (contains(., 'Next') or contains(., 'ถัดไป'))]",
    ]
    for xp in xps:
        els = pager.find_elements(By.XPATH, xp)
        for el in els:
            if el.is_displayed() and el.is_enabled():
                return el
    return None

def first_row_signature(driver, locator, k=3):
    """สร้างลายเซ็นหน้า (เอาแถวบนสุด k แถวรวมข้อความ) เพื่อเช็คว่าเปลี่ยนหน้าแล้วจริง"""
    by, sel = locator
    rows = driver.find_elements(by, sel)[:k]
    parts = []
    for r in rows:
        cells = r.find_elements(By.CSS_SELECTOR, "td") or r.find_elements(By.CSS_SELECTOR, "[role='gridcell']")
        parts.append("|".join([c.text.strip() for c in cells]))
    return "§".join(parts)

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

# ---------- Clean & Save ----------
def extract_thai(text):
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else str(text).strip()

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
    df = df.replace({"-": "", "–": ""})

    file_exists = os.path.exists(CSV_OUT)
    df.to_csv(CSV_OUT, mode="a", index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {len(df)} แถว -> {CSV_OUT}")

# ---------- Main scrape ----------
def scrape_all():
    d = make_driver()
    t0 = time.time()
    try:
        print(f"[INFO] เปิดหน้า: {URL}")
        d.get(URL)
        WebDriverWait(d, 30).until(EC.presence_of_element_located((By.XPATH, "//*")))
        time.sleep(1.0)

        locator = find_rich_table_locator(d)
        pager = find_paginator_root(d)
        if pager:
            set_rows_per_page_100(pager)
            time.sleep(0.5)

        # อ่าน total ถ้าอ่านได้จะคำนวณจำนวนหน้าเลย
        total_start, total_end, total_n = (None, None, None)
        page_size = 100
        pages_plan = None
        if pager:
            txt = get_display_text(pager)
            total_start, total_end, total_n = parse_total_from_display(txt)
            if total_n:
                if total_start and total_end:
                    page_size = max(1, total_end - total_start + 1)
                pages_plan = max(1, math.ceil(total_n / page_size))
                print(f"[INFO] paginator: {txt} -> total={total_n}, page_size={page_size}, pages={pages_plan}")

        all_rows = []
        curdate = datetime.today().strftime("%d/%m/%Y")
        page = 1
        # ใช้ signature เพื่อตรวจว่ามีการเปลี่ยนหน้าแล้วจริง
        sig = first_row_signature(d, locator)

        while True:
            # งบเวลา
            if time.time() - t0 > SCRAPE_BUDGET_SEC:
                print(f"[WARN] หมดงบเวลา {SCRAPE_BUDGET_SEC}s -> หยุดเก็บต่อ")
                break

            time.sleep(0.4)
            rows = get_rows(d, locator)
            # บังคับ 9 คอลัมน์ + ใส่วันที่
            for r in rows:
                r = (r + [""] * 9)[:9]
                r[-1] = curdate
                all_rows.append(r)

            # วางแผนหน้าต่อไป
            if pager:
                # ถ้ารู้จำนวนหน้าแล้ว และเก็บครบแล้ว -> จบ
                if pages_plan and page >= pages_plan:
                    print(f"[INFO] ครบ {page}/{pages_plan} หน้า -> จบ")
                    break
                nxt = find_next_in_pager(pager)
            else:
                nxt = None

            if not nxt:
                print("[INFO] ไม่พบปุ่มถัดไปใน paginator -> จบ")
                break

            # คลิก next และรอจน signature เปลี่ยน
            old_sig = sig
            try:
                d.execute_script("arguments[0].click();", nxt)
                # รอเปลี่ยนหน้า (signature เปลี่ยน / displayedRows เปลี่ยน)
                changed = False
                for _ in range(30):  # ~3s
                    time.sleep(0.1)
                    sig = first_row_signature(d, locator)
                    if sig and sig != old_sig:
                        changed = True
                        break
                if not changed:
                    print("[WARN] คลิกถัดไปแล้วแต่หน้าไม่เปลี่ยน -> จบ")
                    break
                page += 1
                if pager:
                    print(f"[INFO] ไปหน้า {page} / {pages_plan or '?'}")
            except Exception as e:
                print(f"[WARN] ไปหน้าถัดไปไม่สำเร็จ: {e} -> จบ")
                break

        # คัดแถวที่มีอักษรไทยในคอลัมน์ชื่อสถานี (กัน header แฝง)
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
