import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import os
from datetime import datetime

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=options)
driver.get('https://nationalthaiwater.onwr.go.th/dam')

WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

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

        try:
            next_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button"))
            )
            if next_button.is_enabled():
                driver.execute_script("arguments[0].click();", next_button)
                page += 1
                print(f"ไปยังหน้า {page}...")
                time.sleep(2)
            else:
                print(f"จบการดึงข้อมูล: {tab_name}")
                break
        except:
            print(f"ไม่พบปุ่ม 'Next Page' หรือคลิกไม่ได้: {tab_name}")
            break

    return all_data

def save_data_to_csv(data, dam_type):
    if data:
        file_path = f"waterdam_report_{dam_type}.csv"
        file_exists = os.path.exists(file_path)

        df = pd.DataFrame(data)

        # ลบคอลัมน์ที่ไม่มีข้อมูลเลย
        df.replace("", pd.NA, inplace=True)
        df.dropna(axis=1, how='all', inplace=True)

        new_num_cols = df.shape[1]

        if file_exists:
            with open(file_path, encoding="utf-8-sig") as f:
                first_line = f.readline()
                existing_cols = len(first_line.strip().split(","))
            if existing_cols != new_num_cols:
                print(f"โครงสร้างข้อมูลไม่ตรงกับไฟล์เดิม ({existing_cols} ≠ {new_num_cols}) ไม่บันทึก {dam_type}")
                return

        df.to_csv(file_path, mode='a', index=False, encoding="utf-8-sig", header=not file_exists)
        print(f"💾 บันทึกข้อมูล {dam_type} ลงไฟล์ {file_path} แล้ว ({len(df)} แถว)")

large_dam_data = scrape_data("แหล่งน้ำขนาดใหญ่")

# ไปยังแท็บ 'แหล่งน้ำขนาดกลาง' อย่างปลอดภัย
medium_tab_button = WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.XPATH, "//button[@aria-controls='tabpanel-1']"))
)

# รอให้ overlay (เช่น loading screen) หายไปก่อนคลิก
try:
    WebDriverWait(driver, 10).until_not(
        EC.presence_of_element_located((By.CLASS_NAME, "MuiBackdrop-root"))
    )
except:
    pass

# Scroll และคลิกปุ่มแบบปลอดภัย
driver.execute_script("arguments[0].scrollIntoView(true);", medium_tab_button)
time.sleep(1)
driver.execute_script("arguments[0].click();", medium_tab_button)

WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

medium_dam_data = scrape_data("แหล่งน้ำขนาดกลาง")

save_data_to_csv(large_dam_data, "large")
save_data_to_csv(medium_dam_data, "medium")

driver.quit()
