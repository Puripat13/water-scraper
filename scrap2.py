import chromedriver_autoinstaller
chromedriver_autoinstaller.install()

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import pandas as pd
import time
import os

PROXIES = [
    "http://8.213.215.187:443",
    "http://8.213.215.187:3128",
    "http://8.213.222.247:8443",
    "http://8.213.195.191:18080",
    "http://8.213.197.208:8888"
]

def create_driver_with_proxy(proxy):
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument(f'--proxy-server={proxy}')
    return webdriver.Chrome(options=options)

driver = None
for proxy in PROXIES:
    try:
        print(f"🔄 กำลังลองใช้ proxy: {proxy}")
        driver = create_driver_with_proxy(proxy)
        driver.get('https://nationalthaiwater.onwr.go.th/waterlevel')

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
        )
        print("✅ โหลดหน้าเว็บสำเร็จด้วย proxy นี้")
        break
    except Exception as e:
        print(f"❌ Proxy นี้ล้มเหลว: {proxy}\n{e}")
        if driver:
            driver.quit()
            driver = None

if not driver:
    print("🛑 ไม่สามารถเชื่อมต่อเว็บด้วย proxy ใด ๆ ได้")
    exit(1)

try:
    WebDriverWait(driver, 5).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'ยอมรับ')]"))
    ).click()
    print("✅ คลิกยอมรับคุกกี้แล้ว")
except:
    print("❌ ไม่มีปุ่มคุกกี้หรือคลิกไม่สำเร็จ")

try:
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
    )
except Exception:
    print("❌ ไม่พบตารางภายใน 20 วินาที → เขียน debug_page.html")
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    driver.quit()
    exit(1)

start_time = time.time()
all_data = []
current_date = datetime.today().strftime("%d/%m/%Y")

while True:
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
        )
    except:
        print("⚠️ ตารางไม่โหลดในหน้านี้ ข้ามไป...")
        break

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

    try:
        next_button = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@title='Next Page']/span[contains(@class,'MuiIconButton-label')]/.."))
        )
        if next_button.is_enabled():
            driver.execute_script("arguments[0].click();", next_button)
            print("➡️ กด Next Page แล้ว...")
            time.sleep(1)
        else:
            break
    except:
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
    print(f"📁 บันทึกข้อมูลลงไฟล์ {file_path} สำเร็จ!")

driver.quit()
end_time = time.time()
print(f"⏱️ ใช้เวลาในการรันทั้งหมด: {end_time - start_time:.2f} วินาที")
