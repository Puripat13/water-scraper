from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import pandas as pd
import os
from datetime import datetime
import time

options = Options()
options.binary_location = '/usr/bin/chromium-browser'
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--remote-debugging-port=9222')
options.page_load_strategy = 'none'  # ✅ เปิดได้เลย ช่วยข้าม asset JS/CSS

driver = webdriver.Chrome(options=options)
driver.get('https://nationalthaiwater.onwr.go.th/waterlevel')

# รอเฉพาะแถวข้อมูล ไม่รอโหลดหมดทั้งหน้า
WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

start_time = time.time()
max_time = 110  # กันไว้ก่อนเผื่อขั้นตอน save ใช้เวลาอีก 5-10 วิ

all_data = []
current_date = datetime.today().strftime("%d/%m/%Y")

page_count = 0
while True:
    if time.time() - start_time > max_time:
        print("⏱️ ครบเวลาที่กำหนดแล้ว หยุดการดึงข้อมูล")
        break

    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
        )

        rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
        for row in rows:
            cols = [col.text.strip() for col in row.find_elements(By.CSS_SELECTOR, "td")]
            if len(cols) >= 5:
                if len(cols) == 9:
                    cols[-1] = current_date
                else:
                    cols.append(current_date)
                all_data.append(cols)

        # กดปุ่มหน้า next
        next_button_xpath = "//span[@title='Next Page']/button"
        next_button = WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable((By.XPATH, next_button_xpath))
        )
        if next_button.is_enabled():
            driver.execute_script("arguments[0].click();", next_button)
            page_count += 1
        else:
            print("ไม่มีหน้าถัดไปแล้ว")
            break

    except Exception as e:
        print("หยุดเพราะ:", e)
        break

print(f"✅ ดึงข้อมูลจาก {page_count + 1} หน้า ใช้เวลา: {time.time() - start_time:.2f} วินาที")

# จัดการข้อมูล
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
    print(f"📁 บันทึกลงไฟล์ {file_path} เรียบร้อยแล้ว")

driver.quit()
