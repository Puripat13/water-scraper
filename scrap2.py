import time
import re
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# ตั้งค่า ChromeOptions ให้ใช้กับ GitHub Actions
chrome_options = Options()
chrome_options.add_argument("--headless=new")  # run headless
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--remote-debugging-port=9222")

driver = webdriver.Chrome(options=chrome_options)

url = "https://nationalthaiwater.onwr.go.th/waterlevel"
print(f"[INFO] เปิดหน้า: {url}")
driver.get(url)

# รอให้ข้อมูลโหลด
locator = (By.CSS_SELECTOR, ".MuiTable-root tbody tr")
print(f"[INFO] รอโหลดข้อมูล…")
WebDriverWait(driver, 15).until(EC.presence_of_element_located(locator))

rows = driver.find_elements(*locator)
print(f"[INFO] พบ {len(rows)} แถว")

data = []
for row in rows:
    cols = [col.text.strip() for col in row.find_elements(By.TAG_NAME, "td")]
    if cols:
        data.append(cols)

driver.quit()

# แปลงเป็น DataFrame
df = pd.DataFrame(data)

# ✅ Clean ชื่อไทย: ตัดเฉพาะอักษรไทย+เว้นวรรค (ถ้าเจอคอลัมน์ชื่อสถานี)
for col in df.columns:
    if df[col].astype(str).str.contains(r"[ก-๙]").any():
        df[col] = df[col].apply(lambda x: re.sub(r"[^ก-๙\s]", "", str(x)).strip())

# บันทึก CSV
df.to_csv("waterlevel_report.csv", index=False, encoding="utf-8-sig")
print(f"💾 บันทึก {len(df)} แถว, {len(df.columns)} คอลัมน์ -> waterlevel_report.csv")
