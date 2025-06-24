from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import pandas as pd
import os
from datetime import datetime

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=options)
driver.get('https://nationalthaiwater.onwr.go.th/waterlevel')

WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

start_time = time.time()

all_data = []
current_date = datetime.today().strftime("%d/%m/%Y")  

while True:
    time.sleep(2) 
    
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

    next_button_xpath = "//span[@title='Next Page']/button"

    try:
        next_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, next_button_xpath))
        )
        
        if next_button.is_enabled():
            driver.execute_script("arguments[0].click();", next_button)
            print("กด Next Page แล้ว...")
            time.sleep(2)
        else:
            print("ไม่มีหน้าถัดไปแล้ว")
            break

    except Exception:
        print("ไม่พบปุ่ม Next Page หรือปุ่มไม่สามารถกดได้")
        break

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
    
    print(f"บันทึกข้อมูลลงไฟล์ {file_path} สำเร็จ!")

driver.quit()
end_time = time.time() 
print(f"ใช้เวลาในการรันทั้งหมด: {end_time - start_time:.2f} วินาที")
