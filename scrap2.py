import asyncio
from playwright.async_api import async_playwright
import pandas as pd
from datetime import datetime
import os

OUTPUT_FILE = "waterlevel_report.csv"

async def run():
    print("\U0001F30D กำลังโหลดหน้าเว็บ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(
                "https://nationalthaiwater.onwr.go.th/waterlevel",
                wait_until="networkidle",  # เปลี่ยนจาก "load" เป็น "networkidle"
                timeout=180000
            )

            # ✅ คลิกปุ่ม "ยอมรับ" ถ้ามี popup
            try:
                await page.locator("button:has-text(\"ยอมรับ\")").first.click(timeout=5000)
            except:
                pass

            await page.wait_for_selector(".MuiTable-root tbody tr", timeout=20000)

        except Exception as e:
            print(f"โหลดหน้าเว็บไม่สำเร็จ: {e}")
            await browser.close()
            with open(OUTPUT_FILE, "w", encoding="utf-8-sig") as f:
                f.write("ไม่มีข้อมูลที่ดึงได้\n")
            return

        all_data = []
        current_date = datetime.today().strftime("%d/%m/%Y")

        while True:
            await page.wait_for_selector(".MuiTable-root tbody tr", timeout=10000)
            rows = await page.query_selector_all(".MuiTable-root tbody tr")

            print(f"พบ {len(rows)} แถวในตาราง")

            for row in rows:
                cols = await row.query_selector_all("td")
                data = [await col.inner_text() for col in cols]
                if len(data) >= 5:
                    if len(data) == 9:
                        data[-1] = current_date
                    else:
                        data.append(current_date)
                    all_data.append(data)

            next_btn = page.locator("//span[@title='Next Page']/button")
            if await next_btn.is_enabled():
                print("กด Next Page แล้ว...")
                await next_btn.click()
                await page.wait_for_timeout(1000)
            else:
                print("ไม่มีหน้าถัดไปแล้ว")
                break

        if all_data:
            max_columns = max(len(row) for row in all_data)
            all_data = [row + [""] * (max_columns - len(row)) for row in all_data]

            column_names = [
                "ชื่อสถานี", "ที่ตั้ง", "เวลา", "ระดับน้ำ",
                "ระดับตลิ่ง", "ค่าศูนย์เสาระดับ", "%ความจุน้ำ",
                "สถานการณ์", "วันที่เก็บข้อมูล"
            ]
            if len(column_names) < max_columns:
                column_names += [f"เพิ่มเติม_{i+1}" for i in range(max_columns - len(column_names))]

            file_exists = os.path.exists(OUTPUT_FILE)
            df = pd.DataFrame(all_data, columns=column_names)
            df.to_csv(OUTPUT_FILE, mode='a', index=False, encoding="utf-8-sig", header=not file_exists)

            print(f"\U0001F4C4 บันทึกข้อมูลลงไฟล์ {OUTPUT_FILE} สำเร็จ!")
        else:
            print("ไม่พบข้อมูล – สร้างไฟล์เปล่าไว้ให้ GitHub ไม่พัง")
            with open(OUTPUT_FILE, "w", encoding="utf-8-sig") as f:
                f.write("ไม่มีข้อมูลที่ดึงได้\n")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
