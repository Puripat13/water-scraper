from playwright.sync_api import sync_playwright
import pandas as pd
from datetime import datetime
import os
import time

file_path = "waterlevel_report.csv"

def run():
    all_data = []
    current_date = datetime.today().strftime("%d/%m/%Y")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("🌐 กำลังโหลดหน้าเว็บ...")

        try:
            page.goto("https://nationalthaiwater.onwr.go.th/waterlevel", timeout=90000)
            page.wait_for_selector(".MuiTable-root tbody tr", timeout=30000)

            while True:
                rows = page.query_selector_all(".MuiTable-root tbody tr")

                for row in rows:
                    cols = row.query_selector_all("td")
                    data = [col.inner_text().strip() for col in cols]

                    if len(data) < 5:
                        continue

                    if len(data) == 9:
                        data[-1] = current_date
                    else:
                        data.append(current_date)

                    all_data.append(data)

                # ถ้ามีปุ่ม Next → คลิก
                try:
                    next_button = page.query_selector("//span[@title='Next Page']/button")
                    if next_button and not next_button.is_disabled():
                        next_button.click()
                        print("➡️ กด Next Page แล้ว...")
                        time.sleep(1)
                    else:
                        print("✅ ไม่มีหน้าถัดไปแล้ว")
                        break
                except:
                    print("⚠️ ไม่พบปุ่ม Next Page หรือกดไม่ได้")
                    break

        except Exception as e:
            print(f"❌ โหลดหน้าเว็บไม่สำเร็จ: {e}")

        browser.close()

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

if __name__ == "__main__":
    run()

