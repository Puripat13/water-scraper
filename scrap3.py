# -*- coding: utf-8 -*-
# https://nationalthaiwater.onwr.go.th/dam ใช้เก็บข้อมูลแหล่งน้ำ

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

# ---------- Chrome / Selenium ----------
def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1366,900")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--lang=th-TH")
    return webdriver.Chrome(options=opt)  # Selenium Manager จะจัดการไบนารีให้

def wait_table_ready(driver, timeout=20):
    # ตารางมีแถว และไม่มี overlay บัง
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
    """
    ไปแท็บ 'แหล่งน้ำขนาดกลาง' แบบทนทาน:
    - ใช้ aria-controls (เสถียรกว่าการจับ text() ตรง ๆ)
    - scrollIntoView + JS click fallback
    """
    xp = "//button[@aria-controls='tabpanel-1']"
    el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xp)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xp)))
        el.click()
    except (ElementClickInterceptedException, TimeoutException):
        driver.execute_script("arguments[0].click();", el)

def click_next_page(driver, timeout=6):
    """
    คลิก next page ถ้าไปต่อได้
    return: True=มีหน้าใหม่, False=สุดหน้า/คลิกไม่ได้
    """
    try:
        btn = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//span[@title='Next Page']/button"))
        )
        # ถ้าปุ่ม disable ที่ aria-disabled=true ให้หยุด
        disabled = btn.get_attribute("aria-disabled")
        if disabled in ("true", True):
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

# ---------- Scrape core ----------
def scrape_current_tab(driver, tab_label):
    """
    ดึงทุกหน้าในแท็บปัจจุบัน
    คืนค่า list of rows (เติมวันที่และชื่อแท็บท้ายแถวให้เหมือนเดิม)
    """
    all_data, page = [], 1
    current_date = datetime.today().strftime("%d/%m/%Y")

    while True:
        wait_table_ready(driver, timeout=20)
        time.sleep(0.8)  # กันตารางเด้ง re-render

        rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
        count_before = len(all_data)

        for r in rows:
            cols = [td.text.strip() for td in r.find_elements(By.CSS_SELECTOR, "td")]
            if any(c not in ("", "-", None) for c in cols):
                cols += [current_date, tab_label]
                all_data.append(cols)

        new_rows = len(all_data) - count_before
        print(f"[{tab_label}] page {page}: +{new_rows} rows")

        # ถ้าไม่มีหน้าใหม่ให้ไปต่อ -> break
        if not click_next_page(driver):
            print(f"[{tab_label}] reached last page.")
            break

        page += 1
        time.sleep(0.6)  # หน่วงสั้น ๆ ให้ตารางเปลี่ยนหน้า

    return all_data

def save_data_to_csv(data, dam_type):
    """
    บันทึก CSV ที่ root:
      - waterdam_report_large.csv
      - waterdam_report_medium.csv
    โครงสร้างแถว = คอลัมน์จากหน้าเว็บ + [Data_Time, Water_Type] ด้านท้าย
    ถ้ามีไฟล์เดิม: append ต่อท้าย (เฉพาะจำนวนคอลัมน์เท่ากัน)
    """
    if not data:
        print(f"❌ ไม่มีข้อมูล {dam_type}, ข้าม")
        return

    path = f"waterdam_report_{dam_type}.csv"
    exists = os.path.exists(path)

    df = pd.DataFrame(data)
    df.replace("", pd.NA, inplace=True)
    df.dropna(axis=1, how="all", inplace=True)

    # ตรวจจำนวนคอลัมน์กับไฟล์เดิม
    if exists:
        with open(path, encoding="utf-8-sig") as f:
            first_line = f.readline()
        old_cols = len(first_line.strip().split(","))
        if old_cols != df.shape[1]:
            print(f"⚠️ โครงสร้างไม่ตรงไฟล์เดิม ({old_cols} ≠ {df.shape[1]}). จะไม่ append เพื่อกันเพี้ยน")
            # เขียนหัวใหม่ (ทับไฟล์เดิม) — ถ้าอยาก “บังคับคอลัมน์เดิม” ให้ไปทำใน scrap4.py ตอนรวมอีกที
            exists = False

    df.to_csv(path, mode=("a" if exists else "w"),
              index=False, encoding="utf-8-sig", header=not exists)
    print(f"💾 saved {path} (+{len(df)} rows)")

# ---------- Main ----------
def main():
    t0 = time.time()
    driver = make_driver()
    driver.get(URL)

    # รอให้หน้าแรกพร้อม
    wait_table_ready(driver, timeout=25)

    # 1) แหล่งน้ำขนาดใหญ่ (แท็บแรก)
    large_rows = scrape_current_tab(driver, "แหล่งน้ำขนาดใหญ่")
    save_data_to_csv(large_rows, "large")

    # 2) ไปแท็บ 'แหล่งน้ำขนาดกลาง'
    click_medium_tab(driver)
    wait_table_ready(driver, timeout=20)

    medium_rows = scrape_current_tab(driver, "แหล่งน้ำขนาดกลาง")
    save_data_to_csv(medium_rows, "medium")

    driver.quit()
    print(f"⏱️ ทั้งหมด {time.time() - t0:.2f}s")

if __name__ == "__main__":
    main()
