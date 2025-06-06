from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import pandas as pd
import os
from datetime import datetime

# ตั้งค่าความเร็ว Chrome สำหรับ GitHub Actions
options = Options()
options.binary_location = '/usr/bin/chromium-browser'
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.page_load_strategy = 'eager'  # ไม่ต้องรอโหลดทั้งหมด

driver = webdriver.Chrome(options=options)
driver.get('https://nationalthaiwater.onwr.go.th/waterlevel')

WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

all_data = []
current_date = datetime.today().strftime("%d/%m/%Y")  

while True:
    try:
        # รอแถวโหลด (ไม่ต้อง sleep 2 วิ แล้ว)
        WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
        )

        table_rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")

        for row in table_rows:
            cols = row.find_elements(By.CSS_SELECTOR, "td")
            data = [col.text.strip() for col in cols]

            if len(data) < 5:
                continue

            if len(data) == 9:
                data[-1] = current_date
            else:
                data.append(current_date)

            all_data.append(data)

        # พยายามคลิก Next Page โดยไม่รอเกิน 3 วินาที
        next_button_xpath = "//span[@title='Next Page']/button"
        next_button = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, next_button_xpath))
        )

        if next_button.is_enabled():
            driver.execute_script("arguments[0].click();", next_button)
        else:
            break

    except Exception:
        break

# ✅ บันทึกข้อมูล
if all_data:
    max_columns = max(len(row) for row in all_data)
    all_data = [row + [''] * (max_columns - len(row)) for row in all_data]

    column_names = [
        "ชื่อสถานี", "ที่ตั้ง", "เวลา", "ระดับน้ำ",
        "ระดับตลิ่ง", "ค่าศูนย์เสาระดับ", "%ความจุน้ำ",
        "สถานการณ์", "วันที่เก็บข้อมูล"
    ]

    if len(column_names) < max_columns:
        column_names += [f"เพิ่มเติม_{i+1}" for i in range(max_columns - len(column_names))]

    file_path = "waterlevel_report.csv"
    file_exists = os.path.exists(file_path)

    df = pd.DataFrame(all_data, columns=column_names)
    df.to_csv(file_path, mode='a', index=False, encoding="utf-8-sig", header=not file_exists)

driver.quit()

