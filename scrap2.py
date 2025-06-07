from playwright.sync_api import sync_playwright
import pandas as pd
import time

output_file = "waterlevel_report.csv"
data = []

def accept_cookie_if_present(page):
    try:
        page.wait_for_selector("button:has-text('ยอมรับ')", timeout=3000)
        page.click("button:has-text('ยอมรับ')")
        print("\u2705 คลิกปุ่มยอมรับคุกกี้แล้ว")
    except:
        print("\u26A0\uFE0F ไม่พบปุ่มยอมรับคุกกี้ หรือคลิกไม่ได้")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://nationalthaiwater.onwr.go.th/waterlevel", wait_until="domcontentloaded", timeout=90000)

    accept_cookie_if_present(page)
    page.wait_for_selector(".MuiTable-root tbody tr", timeout=30000)

    start = time.time()
    page_count = 0

    while True:
        print(f"\u2B06\uFE0F ดึงข้อมูลจากหน้า {page_count + 1}")
        rows = page.query_selector_all(".MuiTable-root tbody tr")
        for row in rows:
            cols = row.query_selector_all("td")
            row_data = [col.inner_text().strip() for col in cols]
            if len(row_data) >= 5:
                data.append(row_data)

        # ตรวจสอบปุ่ม next page
        next_button = page.query_selector("button[aria-label='Next Page']")
        if next_button and not next_button.is_disabled():
            next_button.click()
            page.wait_for_selector(".MuiTable-root tbody tr")
            page_count += 1
        else:
            break

    browser.close()

# แปลงเป็น DataFrame และบันทึก CSV
max_columns = max(len(row) for row in data)
data = [row + [''] * (max_columns - len(row)) for row in data]

columns = [
    "ชื่อสถานี", "ที่ตั้ง", "เวลา", "ระดับน้ำ", "ระดับตลิ่ง",
    "ค่าศูนย์เสาระดับ", "%ความจุน้ำ", "สถานการณ์", "วันที่เก็บข้อมูล"
]
if len(columns) < max_columns:
    columns += [f"เพิ่มเติม_{i+1}" for i in range(max_columns - len(columns))]

pd.DataFrame(data, columns=columns).to_csv(output_file, index=False, encoding="utf-8-sig")
print(f"\u2705 บันทึกข้อมูลลง {output_file} แล้ว ใช้เวลา {time.time() - start:.2f} วินาที")
