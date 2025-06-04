from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import pandas as pd
import time
import os

options = Options()
options.binary_location = "/usr/bin/google-chrome"
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.page_load_strategy = "eager"

driver = webdriver.Chrome(options=options)
driver.get("https://www.pwa.co.th/province/report")

# ลบ cookie banner ถ้ามี
try:
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "pwa-cookie-consent"))
    )
    driver.execute_script("""
        let el = document.querySelector('.pwa-cookie-consent');
        if (el) el.remove();
    """)
    print("ลบ cookie banner รอบแรกสำเร็จ")
except:
    print("ไม่พบ cookie banner รอบแรก")

months = [str(i) for i in range(1, 13)]
this_year = datetime.now().year
years = [str(y) for y in range(this_year - 3, this_year + 1)]

data_list = []
start_time = time.time()

for year in years:
    for month in months:
        Select(driver.find_element(By.ID, "monthlist")).select_by_value(month)
        Select(driver.find_element(By.ID, "yearlist")).select_by_value(year)

        # ลบ cookie banner ซ้ำ (ถ้ากลับมา)
        try:
            driver.execute_script("""
                let el = document.querySelector('.pwa-cookie-consent');
                if (el) el.remove();
            """)
        except:
            pass

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "btn-primary"))
        ).click()

        # รอให้ตารางโหลด
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".table-hover tbody tr"))
            )
        except:
            print(f"ตารางไม่โหลดเดือน {month} ปี {year}")
            continue

        rows = driver.find_elements(By.CSS_SELECTOR, ".table-hover tbody tr")

        # ตรวจสอบว่าแถวไม่มีข้อมูล (ไม่มี td จริง)
        no_data = True
        for r in range(len(rows)):
            try:
                tds = driver.find_elements(By.CSS_SELECTOR, ".table-hover tbody tr")[r].find_elements(By.TAG_NAME, "td")
                if len(tds) > 1:
                    no_data = False
                    break
            except:
                continue

        if not rows or no_data:
            print(f"ไม่มีข้อมูลในเดือน {month} ปี {year}, ข้ามเดือนนี้")
            if int(year) == this_year:
                print("ถึงเดือนอนาคตของปีปัจจุบันแล้ว หยุด loop")
                break
            continue

        # ดึงข้อมูลจากแถวที่มี td จริง
        for i in range(len(rows)):
            try:
                row = driver.find_elements(By.CSS_SELECTOR, ".table-hover tbody tr")[i]
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 2:
                    continue  # ข้ามแถวที่ไม่มีข้อมูลจริง

                data = [col.text.strip() for col in cols]
                if data:
                    data = [month, year] + data
                    data.append(datetime.now().strftime("%d/%m/%y %H.%M") + " น.")
                    data_list.append(data)
            except Exception as e:
                print(f"ข้ามแถว {i} เดือน {month} ปี {year} เนื่องจาก error: {e}")

        print(f"ดึงข้อมูลเดือน {month} ปี {year} เรียบร้อย")

driver.quit()
end_time = time.time()
print(f"\n⏱️ รวมเวลาทั้งหมดที่ใช้: {end_time - start_time:.2f} วินาที")

columns = [
    "Month", "Year", "No", "Location", "Users", "Prod_Capacity",
    "Water_Produced", "Water_Supplied", "Water_Sold", "Data_Time"
]

file_path = "Water_Production.csv"
file_exists = os.path.exists(file_path) and os.path.getsize(file_path) > 0

df = pd.DataFrame(data_list, columns=columns)

if file_exists:
    try:
        df_existing = pd.read_csv(file_path, encoding="utf-8-sig")
        if list(df_existing.columns) != columns:
            print("ชื่อคอลัมน์ของไฟล์เดิมและข้อมูลใหม่ไม่ตรงกัน! กรุณาตรวจสอบข้อมูล")
        else:
            combined_df = pd.concat([df_existing, df], ignore_index=True)
            combined_df.drop_duplicates(subset=["Month", "Year", "Location"], keep="first", inplace=True)
            if len(combined_df) == len(df_existing):
                print("ไม่มีข้อมูลใหม่เพิ่มเข้ามา ไม่บันทึกไฟล์ซ้ำ")
            else:
                combined_df.to_csv(file_path, index=False, encoding="utf-8-sig")
                print("มีข้อมูลใหม่เพิ่มเข้ามา บันทึกไฟล์สำเร็จ")
    except pd.errors.EmptyDataError:
        print("ไฟล์ CSV ว่างเปล่า สร้างใหม่จากข้อมูลที่ดึงมา")
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        print("บันทึกไฟล์ใหม่สำเร็จ")
else:
    df.to_csv(file_path, index=False, encoding="utf-8-sig")
    print("สร้างไฟล์ใหม่และบันทึกข้อมูลสำเร็จ")
