# -*- coding: utf-8 -*-
import os, time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://nationalthaiwater.onwr.go.th/dam"

def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1366,900")
    return webdriver.Chrome(options=opt)

def scrape_table(driver, tab_xpath, dam_type):
    btn = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, tab_xpath)))
    btn.click()
    time.sleep(2)

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    data = []
    for r in rows:
        cols = [c.text.strip() for c in r.find_elements(By.TAG_NAME, "td")]
        if cols: data.append(cols)
    return data

def save_data_to_csv(data, dam_type):
    if not data:
        print(f"❌ ไม่มีข้อมูล {dam_type}, ข้าม")
        return

    file_path = f"waterdam_report_{dam_type}.csv"
    file_exists = os.path.exists(file_path)

    df = pd.DataFrame(data)

    # ลบคอลัมน์ที่ว่างทั้งคอลัมน์
    df.replace("", pd.NA, inplace=True)
    df.dropna(axis=1, how='all', inplace=True)

    # ---- ตั้งชื่อคอลัมน์มาตรฐาน ----
    base_cols = ["Dam","Location","Capacity_Total","Capacity_Usable",
                 "Water_Stored","Water_Usable","Inflow","Outflow"]
    cols = df.columns.tolist()

    if len(cols) >= 2:
        cols[-2] = "Data_Time"
        cols[-1] = "Water_Type"
    for i, name in enumerate(base_cols[:min(8, len(cols)-2)]):
        cols[i] = name
    df.columns = cols

    # ---- บันทึก ----
    if file_exists:
        old = pd.read_csv(file_path, nrows=0, encoding="utf-8-sig")
        # จัดคอลัมน์ให้ตรงกับไฟล์เดิม
        for c in old.columns:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[old.columns]

    df.to_csv(file_path, mode='a' if file_exists else 'w',
              index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึก {file_path} แล้ว ({len(df)} แถว)")

def main():
    driver = make_driver()
    driver.get(URL)
    time.sleep(5)

    # Large
    large_data = scrape_table(driver, "//button[contains(text(),'เขื่อนขนาดใหญ่')]", "large")
    save_data_to_csv(large_data, "large")

    # Medium
    medium_data = scrape_table(driver, "//button[contains(text(),'เขื่อนขนาดกลาง')]", "medium")
    save_data_to_csv(medium_data, "medium")

    driver.quit()

if __name__ == "__main__":
    main()
