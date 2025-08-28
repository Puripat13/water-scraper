# -*- coding: utf-8 -*-
import os, time
import pandas as pd
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

URL = "https://nationalthaiwater.onwr.go.th/dam"

# อ่านค่าเพดานหน้าจาก ENV (เช่น SCRAPE_MAX_PAGES=400) – ถ้าไม่ตั้งจะไม่จำกัด
SCRAPE_MAX_PAGES = int(os.getenv("SCRAPE_MAX_PAGES", "0"))

def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1366,900")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--lang=th-TH")
    return webdriver.Chrome(options=opt)

def wait_table_ready(driver, timeout=20):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
    )
    try:
        WebDriverWait(driver, 5).until_not(
            EC.presence_of_element_located((By.CLASS_NAME, "MuiBackdrop-root"))
        )
    except TimeoutException:
        pass

def click_medium_tab(driver, timeout=20):
    xp = "//button[@aria-controls='tabpanel-1']"
    el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xp)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xp)))
        el.click()
    except (ElementClickInterceptedException, TimeoutException):
        driver.execute_script("arguments[0].click();", el)

def click_next_page(driver, timeout=6):
    try:
        btn = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//span[@title='Next Page']/button"))
        )
        if btn.get_attribute("aria-disabled") in ("true", True):
            return False
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        try:
            WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button")))
            btn.click()
        except (ElementClickInterceptedException, TimeoutException):
            driver.execute_script("arguments[0].click();", btn)
        return True
    except TimeoutException:
        return False

def append_rows_to_csv(rows, tab_label, csv_path, is_first_write):
    if not rows:
        return 0
    current_date = datetime.today().strftime("%d/%m/%Y")
    # เติมวันที่/ชื่อแท็บท้ายแถวแบบเดิม
    rows2 = [r + [current_date, tab_label] for r in rows if any(c not in ("", "-", None) for c in r)]
    if not rows2:
        return 0
    df = pd.DataFrame(rows2)
    # ล้างคอลัมน์ว่างทั้งคอลัมน์ (ถ้ามี)
    df.replace("", pd.NA, inplace=True)
    df.dropna(axis=1, how="all", inplace=True)
    df.to_csv(csv_path, mode=("w" if is_first_write else "a"),
              index=False, encoding="utf-8-sig", header=is_first_write)
    return len(df)

def scrape_tab_to_csv(driver, tab_label, csv_path):
    """ดึงทุกหน้าในแท็บปัจจุบันและ 'เขียนไฟล์ทีละหน้า' เพื่อกันพลาดตอน timeout/cancel"""
    # เริ่มไฟล์ใหม่ทุกครั้ง (ให้ผลของรันล่าสุดสมบูรณ์)
    if os.path.exists(csv_path):
        os.remove(csv_path)
    page, first_write = 1, True
    total = 0

    while True:
        wait_table_ready(driver, timeout=25)
        time.sleep(0.4)  # กัน re-render

        rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
        # เก็บค่าคอลัมน์ดิบก่อน (ยังไม่เติมวันที่/แท็บ)
        page_rows = [[td.text.strip() for td in r.find_elements(By.CSS_SELECTOR, "td")] for r in rows]

        wrote = append_rows_to_csv(page_rows, tab_label, csv_path, is_first_write=first_write)
        first_write = False
        total += wrote
        print(f"[{tab_label}] page {page}: +{wrote} rows (total={total})")

        if SCRAPE_MAX_PAGES and page >= SCRAPE_MAX_PAGES:
            print(f"[{tab_label}] reached SCRAPE_MAX_PAGES={SCRAPE_MAX_PAGES}, stop.")
            break

        if not click_next_page(driver):
            print(f"[{tab_label}] reached last page.")
            break

        page += 1
        time.sleep(0.4)

    if total == 0:
        print(f"⚠️ {tab_label}: no rows written.")
    else:
        print(f"✅ {tab_label}: wrote {total} rows -> {csv_path}")

def main():
    t0 = time.time()
    driver = make_driver()
    driver.get(URL)
    wait_table_ready(driver, timeout=30)

    # 1) แหล่งน้ำขนาดใหญ่
    scrape_tab_to_csv(driver, "แหล่งน้ำขนาดใหญ่", "waterdam_report_large.csv")

    # 2) แหล่งน้ำขนาดกลาง
    click_medium_tab(driver)
    wait_table_ready(driver, timeout=25)
    scrape_tab_to_csv(driver, "แหล่งน้ำขนาดกลาง", "waterdam_report_medium.csv")

    driver.quit()
    print(f"⏱️ total {time.time() - t0:.2f}s")

if __name__ == "__main__":
    main()
