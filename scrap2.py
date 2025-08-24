from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
from datetime import datetime

# === ตั้งค่า WebDriver ===
driver = webdriver.Chrome()
driver.get('https://nationalthaiwater.onwr.go.th/waterlevel')

wait = WebDriverWait(driver, 10)

print("[INFO] รอให้ตารางโหลด...")
wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr")))

all_rows = []  # เก็บข้อมูลทุกหน้า
page = 1

while True:
    print(f"[INFO] Page {page} ...")

    # ดึงทุกแถวในหน้านี้
    rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
    print(f"[INFO] เจอ {len(rows)} แถว")
    
    for row in rows:
        cols = [c.text.strip() for c in row.find_elements(By.TAG_NAME, "td")]
        all_rows.append(cols)

    # === หาปุ่มถัดไป ===
    try:
        next_btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Go to next page']")
        
        # ถ้าปุ่มกดไม่ได้ (disabled) ให้จบ loop
        if not next_btn.is_enabled():
            print("[INFO] ปุ่มถัดไปกดไม่ได้แล้ว -> จบการดึงข้อมูล")
            break
        
        # ถ้ากดได้ → คลิกไปหน้าถัดไป
        driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(2)  # หน่วงให้ตารางโหลด
        page += 1

    except Exception as e:
        print("[INFO] ไม่เจอปุ่มถัดไป -> จบการดึงข้อมูล")
        break

# === บันทึก CSV ===
columns = [
    "Station", "Location", "Time", "Water_Level", "Bank_Level",
    "Gauge_Zero", "Capacity_Percent", "Status", "Data_Time"
]

df = pd.DataFrame(all_rows, columns=columns[:len(all_rows[0])])

filename = "waterlevel_report.csv"
df.to_csv(filename, index=False, encoding="utf-8-sig")
print(f"💾 บันทึก {len(df)} แถว -> {filename}")

driver.quit()
