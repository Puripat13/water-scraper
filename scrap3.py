# -*- coding: utf-8 -*-
import os
import time
from datetime import datetime
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# ---------------- Selenium Setup ----------------
options = Options()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1366,840')

driver = webdriver.Chrome(options=options)
driver.get("https://nationalthaiwater.onwr.go.th/dam")

WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

start_time = time.time()


# ---------------- ฟังก์ชันดึงข้อมูล ----------------
def scrape_data(tab_name):
    all_data = []
    current_date = datetime.today().strftime("%d/%m/%Y")
    page = 1

    print(f"\nเริ่มดึงข้อมูล: {tab_name}")

    while True:
        time.sleep(2)
        rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
        count_before = len(all_data)

        for row in rows:
            cols = [col.text.strip() for col in row.find_elements(By.CSS_SELECTOR, "td")]
            if any(col not in ("", "-", None) for col in cols):
                cols += [current_date, tab_name]
                all_data.append(cols)

        count_after = len(all_data)
        scraped_this_page = count_after - count_before
        print(f"หน้า {page}: เก็บข้อมูลแล้ว {scraped_this_page} แถว")

        # กด next page ถ้ามี
        try:
            next_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button"))
            )
            if next_button.is_enabled():
                driver.execute_script("arguments[0].click();", next_button)
                page += 1
                time.sleep(2)
            else:
                break
        except:
            break

    return all_data


# ---------------- ฟังก์ชันบันทึก CSV ----------------
def save_data_to_csv(data, dam_type):
    if not data:
        print(f"⚠️ ไม่มีข้อมูล {dam_type}")
        return None

    file_path = f"waterdam_report_{dam_type}.csv"
    file_exists = os.path.exists(file_path)

    df_new = pd.DataFrame(data)
    df_new.replace("", pd.NA, inplace=True)
    df_new.dropna(axis=1, how="all", inplace=True)

    if file_exists:
        df_old = pd.read_csv(file_path, dtype=str)

        # ใช้เฉพาะคอลัมน์ที่ไฟล์เก่ามี
        common_cols = [c for c in df_old.columns if c in df_new.columns]
        df_new = df_new[common_cols]

        # รวมข้อมูลแล้วลบแถวซ้ำ
        df_all = pd.concat([df_old, df_new], ignore_index=True)
        df_all.drop_duplicates(keep="last", inplace=True)

        df_all.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"✅ Append ต่อไฟล์ {file_path} แล้ว (รวม {len(df_all)} แถว)")

    else:
        # ไม่มีไฟล์เก่า → สร้างใหม่จากข้อมูล scrape
        df_new.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"💾 สร้างไฟล์ใหม่ {file_path} ({len(df_new)} แถว)")

    return file_path


# ---------------- เริ่มดึงข้อมูล ----------------
large_dam_data = scrape_data("แหล่งน้ำขนาดใหญ่")

# ไปแท็บ "แหล่งน้ำขนาดกลาง"
medium_tab_button = WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.XPATH, "//button[@aria-controls='tabpanel-1']"))
)
try:
    WebDriverWait(driver, 10).until_not(
        EC.presence_of_element_located((By.CLASS_NAME, "MuiBackdrop-root"))
    )
except:
    pass
driver.execute_script("arguments[0].scrollIntoView(true);", medium_tab_button)
time.sleep(1)
driver.execute_script("arguments[0].click();", medium_tab_button)
WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

medium_dam_data = scrape_data("แหล่งน้ำขนาดกลาง")

# ---------------- บันทึก ----------------
save_data_to_csv(large_dam_data, "large")
save_data_to_csv(medium_dam_data, "medium")

driver.quit()
end_time = time.time()
print(f"\n⏱️ ใช้เวลาในการรันทั้งหมด: {end_time - start_time:.2f} วินาที")
