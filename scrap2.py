from __future__ import annotations

# ============================== 1) IMPORTS & CONFIG ==============================
import os, re, time
from datetime import datetime
from typing import List, Optional

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ------------------------------- Runtime Config --------------------------------
URL: str = os.getenv("WATERLEVEL_URL", "https://nationalthaiwater.onwr.go.th/waterlevel")
CSV_OUT: str = os.getenv("CSV_OUT", "waterlevel_report.csv")

PAGE_TIMEOUT: int = int(os.getenv("PAGE_TIMEOUT", "25"))
CLICK_TIMEOUT: int = int(os.getenv("CLICK_TIMEOUT", "10"))
SLEEP_BETWEEN_PAGES: float = float(os.getenv("SLEEP_BETWEEN_PAGES", "0"))  # ✅ เร็วสุด = 0
MAX_PAGES: int = int(os.getenv("MAX_PAGES", "0"))  # 0 = ไม่จำกัด (ตั้ง 3-5 ตอนเทสต์)

# ============================= 2) Selenium (เร็ว/กัน timeout) =============================
def make_driver() -> webdriver.Chrome:
    opt = Options()
    opt.page_load_strategy = "none"  # ✅ ไม่รอโหลดทั้งหน้า
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1440,900")
    opt.add_argument("--disable-background-networking")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--no-first-run")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    )
    drv = webdriver.Chrome(options=opt)
    drv.set_script_timeout(120)
    return drv

def open_url_with_retry(driver: webdriver.Chrome, url: str, tries: int = 3, wait_css: str = ".MuiTable-root tbody tr", wait_sec: int = PAGE_TIMEOUT):
    last_err = None
    for i in range(1, tries + 1):
        try:
            driver.get("about:blank")
            driver.get(url)
            WebDriverWait(driver, wait_sec).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_css))
            )
            return
        except Exception as e:
            last_err = e
            print(f"⚠️ open_url attempt {i}/{tries} failed: {repr(e)}")
            time.sleep(1.5 * i)
    raise last_err

def _set_rows_per_page(driver: webdriver.Chrome, target_values=(200, 100, 50)):
    """พยายามตั้ง Rows per page ให้มากที่สุด เพื่อลดจำนวนหน้า"""
    open_xpaths = [
        "//div[contains(@class,'MuiTablePagination')]/div[contains(@class,'MuiInputBase-root')]//div[@role='button']",
        "//div[contains(@class,'MuiTablePagination')]/div[contains(@class,'MuiSelect-root')]",
        "//div[contains(@class,'MuiTablePagination')][.//p[contains(.,'Rows per page')]]//div[@role='button']",
        "//div[contains(@class,'MuiTablePagination')]//input[contains(@class,'MuiSelect')]/ancestor::div[@role='button']",
    ]
    opened = False
    for xp in open_xpaths:
        try:
            el = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].click();", el)
            opened = True
            break
        except Exception:
            continue
    if not opened:
        print("ℹ️ ไม่พบเมนู Rows per page (ข้าม)")
        return

    for val in target_values:
        for xp in (f"//li[normalize-space()='{val}']",
                   f"//ul//li[normalize-space()='{val}']",
                   f"//div[@role='listbox']//li[normalize-space()='{val}']"):
            try:
                li = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xp)))
                driver.execute_script("arguments[0].click();", li)
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
                )
                print(f"✅ Rows per page set to {val}")
                return
            except Exception:
                continue
    print("ℹ️ เปลี่ยน Rows per page ไม่สำเร็จ (อาจไม่มีตัวเลือกนี้)")

def _find_next_button(driver: webdriver.Chrome):
    xpaths = [
        "//button[@aria-label='Go to next page']",
        "//span[@title='Next Page']/button",
        "//button[.//span[contains(@class,'MuiSvgIcon-root')]][@aria-label='Next Page']",
    ]
    for xp in xpaths:
        try:
            btn = WebDriverWait(driver, CLICK_TIMEOUT).until(EC.presence_of_element_located((By.XPATH, xp)))
            if btn:
                return btn
        except Exception:
            continue
    return None

def _is_disabled(btn) -> bool:
    try:
        if btn.get_attribute("disabled") in ("true", "disabled"):
            return True
        if btn.get_attribute("aria-disabled") in ("true", "disabled"):
            return True
    except Exception:
        pass
    return False

# ============================= 3) Scrape & Save =============================
def scrape_waterlevel() -> list[list[str]]:
    driver = make_driver()
    try:
        open_url_with_retry(driver, URL, tries=3, wait_css=".MuiTable-root tbody tr", wait_sec=PAGE_TIMEOUT)

        # ลดจำนวนหน้าให้มากที่สุด
        try:
            _set_rows_per_page(driver, target_values=(200, 100, 50))
        except Exception as e:
            print("ℹ️ ข้ามการตั้ง Rows per page:", e)

        def _get_rows():
            return driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")

        all_data: list[list[str]] = []
        current_date = datetime.now().strftime("%m/%d/%y")

        page_idx = 1
        while True:
            rows = _get_rows()
            for row in rows:
                cols = [c.text.strip() for c in row.find_elements(By.CSS_SELECTOR, "td")]
                if len(cols) < 5:
                    continue
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

            if MAX_PAGES and page_idx >= MAX_PAGES:
                print(f"⛔️ Reach MAX_PAGES={MAX_PAGES}, stop early for speed.")
                break

            next_btn = _find_next_button(driver)
            if not next_btn or _is_disabled(next_btn):
                break

            first_old = rows[0] if rows else None
            try:
                driver.execute_script("arguments[0].click();", next_btn)
            except Exception:
                try:
                    next_btn.click()
                except Exception:
                    break

            if first_old is not None:
                try:
                    WebDriverWait(driver, PAGE_TIMEOUT).until(EC.staleness_of(first_old))
                except Exception:
                    pass

            WebDriverWait(driver, PAGE_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
            )
            if SLEEP_BETWEEN_PAGES > 0:
                time.sleep(SLEEP_BETWEEN_PAGES)

            page_idx += 1
            print(f"➡️ Next Page Loaded: {page_idx}")

        return all_data
    finally:
        driver.quit()

def extract_thai(text: str) -> str:
    if pd.isna(text) or text is None:
        return ""
    m = re.search(r"[ก-๙].*", str(text))
    return m.group(0).strip() if m else str(text).strip()

def save_csv(all_data: list[list[str]], out_path: str) -> int:
    if not all_data:
        print("⚠️ ไม่พบข้อมูลให้บันทึก")
        return 0

    max_cols = max(len(r) for r in all_data)
    all_data = [r + [""] * (max_cols - len(r)) for r in all_data]

    headers = [
        "Station","Location","Time","Water_Level","Bank_Level",
        "Gauge_Zero","Capacity_Percent","Status","Data_Time",
    ]
    if len(headers) < max_cols:
        headers += [f"Extra_{i + 1}" for i in range(max_cols - len(headers))]

    df = pd.DataFrame(all_data, columns=headers)
    df["Station"] = df["Station"].apply(extract_thai)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"💾 บันทึก {len(df)} แถว -> {os.path.abspath(out_path)}")
    return len(df)

# ==================================== 4) Main ====================================
def main() -> None:
    t0 = time.time()
    all_data = scrape_waterlevel()
    rows_saved = save_csv(all_data, CSV_OUT)
    elapsed = time.time() - t0
    print(f"⏱ เสร็จสิ้น: บันทึก {rows_saved} แถว ใช้เวลา {elapsed:.2f} วินาที")

if __name__ == "__main__":
    main()
