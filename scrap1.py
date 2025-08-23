# tmd_forecast_today_all.py
# -*- coding: utf-8 -*-

import os, time, random
from datetime import datetime
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

HOME = os.getenv("TMD_HOME", "https://www.tmd.go.th")
CSV_OUT = os.getenv("CSV_OUT", "tmd_7day_forecast_today.csv")


# ============ Driver (ปรับเพื่อลดโหลด) ============
def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--disable-infobars")
    opt.add_argument("--window-size=1366,768")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--remote-allow-origins=*")
    opt.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    # โหลดแบบไม่ต้องรอทุก resource
    opt.page_load_strategy = "none"

    # บล็อค resource หนัก
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.fonts": 2,
        "profile.managed_default_content_settings.plugins": 2,
        "profile.managed_default_content_settings.popups": 2,
        "profile.managed_default_content_settings.notifications": 2,
        "profile.managed_default_content_settings.autoplay": 2,
    }
    opt.add_experimental_option("prefs", prefs)

    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(20)
    drv.set_script_timeout(20)
    return drv


def safe_get(driver, url, timeout=20):
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass


def js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


def click_if_present(driver, by, selector, timeout=6):
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))
        js_click(driver, el)
        return True
    except:
        return False


# ============ Entry / Cookie ============
def bypass_eventday_cookie(driver):
    # ปุ่มเข้าเว็บ / ยอมรับคุกกี้ (ถ้ามี)
    for xp in ["//button[contains(text(),'เข้าสู่เว็บไซต์')]", "//a[contains(text(),'เข้าสู่เว็บไซต์')]"]:
        if click_if_present(driver, By.XPATH, xp, 4):
            break
    for xp in ["//button[contains(text(),'ยอมรับทั้งหมด')]", "//button[contains(text(),'ยอมรับ')]"]:
        if click_if_present(driver, By.XPATH, xp, 3):
            break


def open_home_ready(driver):
    for _ in range(3):
        safe_get(driver, HOME, timeout=12)
        bypass_eventday_cookie(driver)
        try:
            # แค่รอให้ select2 container โผล่
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "select2-province-selector-container"))
            )
            return True
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
                driver.refresh()
            except Exception:
                pass
    # debug dump เผื่อใช้ดูทีหลัง
    try:
        with open("debug_tmd_home.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot("debug_tmd_home.png")
    except Exception:
        pass
    raise TimeoutError("ไม่พบ select2 จังหวัดบนหน้าแรก TMD")


# ============ Select2 Helpers (เร็วขึ้น) ============
def _collect_select2_mapping_fast(driver):
    """
    เปิด dropdown ครั้งเดียว, scroll ให้สุด, เก็บ mapping (name -> value)
    เพื่อต่อไปจะ set ผ่าน JS โดยตรง (เร็วกว่าเปิด/ค้น/คลิกทุกรอบ)
    """
    # เปิดกล่อง
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "select2-province-selector-container"))
    ).click()

    # ช่องค้นหาโผล่ = dropdown เปิดแล้ว
    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input.select2-search__field"))
    )
    results = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "select2-province-selector-results"))
    )

    # scroll จนรายการคงที่
    stable = 0
    last_cnt = -1
    while True:
        items = results.find_elements(By.CSS_SELECTOR, "li.select2-results__option")
        cnt = len(items)
        if cnt == last_cnt:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
            last_cnt = cnt
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", results)
        time.sleep(0.15)

    mapping = {}
    for li in items:
        name = li.text.strip()
        if not name:
            continue
        # พยายามเดาค่า value จาก id ของ li (pattern ทั่วไป select2-<select>-result-*-<value>)
        li_id = li.get_attribute("id") or ""
        value = li_id.split("-")[-1] if "-" in li_id else name
        mapping[name] = value

    # ปิด dropdown
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    return mapping


def _js_set_select2_value(driver, value):
    """
    พยายาม set ค่า select2 ผ่าน JS ให้เร็วสุด
    สมมติ select element จริงชื่อ 'province-selector' (กรณีเว็บเปลี่ยน อาจไม่สำเร็จ → fallback)
    """
    js = """
    var sel = document.getElementById('province-selector');
    if (!sel) return false;
    sel.value = arguments[0];
    var ev = new Event('change', { bubbles: true });
    sel.dispatchEvent(ev);
    return true;
    """
    try:
        return bool(driver.execute_script(js, value))
    except Exception:
        return False


def select_province_fast(driver, name, mapping):
    """
    เร็ว: ใช้ JS set value ถ้าไม่ได้ค่อย fallback ไปวิธีเดิม (ค้นหา+คลิก)
    """
    value = mapping.get(name)
    if value and _js_set_select2_value(driver, value):
        # รอให้คอนเทนต์โหลด/อัพเดต
        time.sleep(0.15)
        return True

    # --- fallback เดิม (ค้นหา+คลิก) ---
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "select2-province-selector-container"))
    ).click()
    search = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input.select2-search__field"))
    )
    search.clear()
    search.send_keys(name)
    # รอสั้นๆ ให้ผลลัพธ์กรองเสร็จ
    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.XPATH,
            ("//li[contains(@class,'select2-results__option') and "
             "normalize-space(text())='{0}']").format(name)))
    )
    js_click(driver, driver.find_element(
        By.XPATH,
        ("//li[contains(@class,'select2-results__option') and "
         "normalize-space(text())='{0}']").format(name)
    ))
    # ปล่อยให้หน้าอัปเดต
    time.sleep(0.1)
    return True


# ============ Parse "วันนี้" แบบเร็ว (ไม่ใช้ bs4) ============
def parse_today_fast(driver, province_name):
    # card วันนี้
    # หา card ที่มีหัว "วันนี้"
    cards = driver.find_elements(By.CSS_SELECTOR, "div.card.card-shadow.text-center")
    for c in cards:
        try:
            head = c.find_element(By.CSS_SELECTOR, "div.font-small")
            if head.text.strip() != "วันนี้":
                continue

            date_txt = c.find_element(By.CSS_SELECTOR, "div.font-tiny.text-dark2").text.strip()

            # อุณหภูมิ สูง/ต่ำ
            twrap = c.find_element(By.CSS_SELECTOR, "div.d-flex.justify-content-around.sub-heading")
            dvals = twrap.find_elements(By.CSS_SELECTOR, "div")
            tmax = dvals[0].text.strip() if len(dvals) > 0 else ""
            tmin = dvals[2].text.strip() if len(dvals) > 2 else ""

            tinys = c.find_elements(By.CSS_SELECTOR, "div.font-tiny.text-center")
            cond = tinys[0].text.strip() if len(tinys) > 0 else ""
            rain = tinys[1].text.strip() if len(tinys) > 1 else ""
            wind = ""
            try:
                wind = c.find_element(By.CSS_SELECTOR, "span.font-tiny.ps-1").text.strip()
            except Exception:
                pass

            return {
                "จังหวัด/รายการ": province_name,
                "วันที่": date_txt,
                "อุณหภูมิสูงสุด": tmax,
                "อุณหภูมิต่ำสุด": tmin,
                "สภาพอากาศ": cond,
                "โอกาสฝน": rain,
                "ลม": wind,
                "เวลาบันทึก": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception:
            continue
    return None


# ============ Main ============
def main():
    driver = make_driver()
    rows, failed = [], []
    try:
        open_home_ready(driver)

        # เตรียม mapping สำหรับเลือกจังหวัดด้วย JS (เปิด dropdown แค่ครั้งเดียว)
        mapping = _collect_select2_mapping_fast(driver)

        names = list(mapping.keys())
        print(f"รายการจาก select2 ทั้งหมด: {len(names)} รายการ")

        for i, name in enumerate(names, 1):
            ok = False
            for attempt in range(2):
                try:
                    # เลือกจังหวัดแบบเร็ว
                    select_province_fast(driver, name, mapping)

                    # รอให้ card "วันนี้" โผล่จริง ๆ (หน้าเพิ่งอัปเดต)
                    WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.card.card-shadow.text-center"))
                    )

                    row = parse_today_fast(driver, name)
                    if row:
                        rows.append(row); ok = True
                        if i % 10 == 0 or i <= 5:
                            print(f"[{i}/{len(names)}] {name} ✔")
                        break
                except Exception as e:
                    if attempt == 0:
                        # refresh เร็วๆ ครั้งเดียว
                        try:
                            driver.execute_script("window.stop();")
                            driver.refresh()
                        except Exception:
                            pass
                    else:
                        print(f"[{i}/{len(names)}] {name} ✖ {e}")
            if not ok:
                failed.append(name)

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if rows:
        df = pd.DataFrame(rows)
        keep_cols = ["จังหวัด/รายการ", "สภาพอากาศ", "โอกาสฝน", "เวลาบันทึก"]
        df = df[keep_cols].rename(columns={
            "จังหวัด/รายการ": "Province",
            "สภาพอากาศ": "Weather",
            "โอกาสฝน": "RainChance",
            "เวลาบันทึก": "DateTime"
        })
        df["RainChance"] = (
            df["RainChance"].astype(str)
            .str.extract(r'(\d+)')[0]
            .astype(float)
            .div(100)
        )

        file_exists = os.path.exists(CSV_OUT)
        df.to_csv(
            CSV_OUT,
            mode="a",
            header=not file_exists,
            index=False,
            encoding="utf-8-sig"
        )
        print(f"\n✅ บันทึก {len(df)} แถว ต่อท้ายไฟล์: {CSV_OUT}")

    if failed:
        print("\nรายการที่ดึงไม่สำเร็จ:", ", ".join(failed))


if __name__ == "__main__":
    main()
