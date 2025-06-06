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
options.binary_location = "/usr/bin/google-chrome"
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')
options.add_argument('--remote-debugging-port=9222')
options.page_load_strategy = "eager"

driver = webdriver.Chrome(options=options)
driver.set_page_load_timeout(60)

try:
    for attempt in range(3):
        try:
            print(f"🌐 กำลังโหลดหน้าเว็บ... (รอบที่ {attempt+1})")
            driver.get('https://nationalthaiwater.onwr.go.th/waterlevel')
            break
        except Exception as e:
            print(f"⚠️ โหลดหน้าเว็บไม่สำเร็จในรอบที่ {attempt+1}: {e}")
            if attempt == 2:
                raise
            time.sleep(5)

    # ✅ กดปุ่มยอมรับ Cookie ถ้ามี
    try:
        consent_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.MuiButton-contained"))
        )
        consent_button.click()
        print("✅ กดปุ่มยอมรับ Cookie แล้ว")
    except Exception:
        print("⏩ ไม่มีปุ่ม Cookie หรือคลิกไม่ได้ — ข้ามไป")

    # ✅ รอโหลดตาราง
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
    )

    all_data = []
    current_date = datetime.today().strftime("%d/%m/%Y")

    while True:
        WebDriverWait(driver, 10).until(
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

        next_button_xpath = "//span[@title='Next Page']/button"
        try:
            next_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, next_button_xpath))
            )
            if next_button.is_enabled():
                driver.execute_script("arguments[0].click();", next_button)
                print("➡️ กด Next Page แล้ว...")
                time.sleep(1)
            else:
                print("✅ ไม่มีหน้าถัดไปแล้ว")
                break
        except Exception:
            print("⚠️ ไม่พบปุ่ม Next Page หรือปุ่มไม่สามารถกดได้")
            break

    file_path = "waterlevel_report.csv"

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

        file_exists = os.path.exists(file_path)
        df = pd.DataFrame(all_data, columns=column_names)
        df.to_csv(file_path, mode='a', index=False, encoding="utf-8-sig", header=not file_exists)

        print(f"📄 บันทึกข้อมูลลงไฟล์ {file_path} สำเร็จ!")
    else:
        print("❌ ไม่พบข้อมูล – สร้างไฟล์เปล่าไว้ให้ GitHub ไม่พัง")
        with open(file_path, "w", encoding="utf-8-sig") as f:
            f.write("ไม่มีข้อมูลที่ดึงได้\n")

except Exception as e:
    print(f"❌ เกิดข้อผิดพลาด: {e}")

finally:
    driver.quit()

