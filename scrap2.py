import asyncio
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
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

success = False
for proxy in PROXIES:
    print(f"🔄 กำลังลองใช้ proxy: {proxy}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(proxy={
                "server": proxy
            })
            page = context.new_page()
            page.set_default_timeout(60000)  # 60 วินาที

            page.goto("https://nationalthaiwater.onwr.go.th/waterlevel")

            print(f"📄 Title: {page.title()}")
            print(f"🌐 URL: {page.url}")
            print("📄 HTML ที่โหลด (1,000 ตัวอักษรแรก):")
            print(page.content()[:1000])

            try:
                page.click("button:has-text('ยอมรับ')", timeout=5000)
                print("✅ คลิกปุ่มคุกกี้แล้ว")
            except:
                print("ℹ️ ไม่มีปุ่มคุกกี้ หรือไม่สามารถคลิกได้")

            print("⏳ รอตารางแสดงผลสูงสุด 60 วินาที...")
            page.wait_for_selector(".MuiTable-root tbody tr", timeout=60000)

            all_data = []
            current_date = datetime.today().strftime("%d/%m/%Y")

            while True:
                rows = page.query_selector_all(".MuiTable-root tbody tr")
                print(f"🔎 พบ {len(rows)} แถวในหน้านี้")
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

                try:
                    next_button = page.query_selector("button[title='Next Page']")
                    if next_button and not next_button.is_disabled():
                        next_button.click()
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

            else:
                print("⚠️ โหลดหน้าเว็บได้แต่ไม่พบข้อมูลในตาราง")
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                page.screenshot(path="debug_screenshot.png", full_page=True)
                print("📝 บันทึก debug_page.html และ debug_screenshot.png แล้ว")

            context.close()
            browser.close()
            success = True
            break

    except PlaywrightTimeout:
        print("❌ Timeout ในการโหลดหน้าเว็บ")
    except Exception as e:
        print(f"❌ Proxy นี้ล้มเหลว: {proxy}\n{e}")

if not success:
    print("🛑 ล้มเหลวในการโหลดตารางจากทุก proxy")

    fallback_path = "waterlevel_report.csv"
    if not os.path.exists(fallback_path):
        with open(fallback_path, "w", encoding="utf-8-sig") as f:
            f.write("ข้อความ,ไม่มีข้อมูลให้บันทึก\n")
        print(f"📄 เขียนไฟล์ placeholder: {fallback_path}")

    exit(0)
