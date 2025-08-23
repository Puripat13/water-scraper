# tmd_forecast_today_all.py
# -*- coding: utf-8 -*-

import os, time, random
from datetime import datetime
import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

HOME = os.getenv("TMD_HOME", "https://www.tmd.go.th")
CSV_OUT = os.getenv("CSV_OUT", "tmd_7day_forecast_today.csv")


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
    opt.page_load_strategy = "none"
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


def bypass_eventday_cookie(driver):
    for xp in ["//button[contains(text(),'เข้าสู่เว็บไซต์')]", "//a[contains(text(),'เข้าสู่เว็บไซต์')]"]:
        if click_if_present(driver, By.XPATH, xp, 5):
            break
    for xp in ["//button[contains(text(),'ยอมรับทั้งหมด')]", "//button[contains(text(),'ยอมรับ')]"]:
        if click_if_present(driver, By.XPATH, xp, 3):
            break


def open_home_ready(driver):
    for _ in range(4):
        safe_get(driver, HOME, timeout=15)
        bypass_eventday_cookie(driver)
        try:
            WebDriverWait(driver, 40).until(
                EC.presence_of_element_located((By.ID, "select2-province-selector-container"))
            )
            return True
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
                driver.refresh()
            except Exception:
                pass
            time.sleep(1.2)

    with open("debug_tmd_home.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    try:
        driver.save_screenshot("debug_tmd_home.png")
    except Exception:
        pass
    raise TimeoutError("ไม่พบ select2 จังหวัดบนหน้าแรก TMD")


def collect_all_select2_items(driver):
    WebDriverWait(driver, 12).until(
        EC.element_to_be_clickable((By.ID, "select2-province-selector-container"))
    ).click()

    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input.select2-search__field"))
    )
    results = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "select2-province-selector-results"))
    )

    last, stable = -1, 0
    while True:
        items = results.find_elements(By.CSS_SELECTOR, "li.select2-results__option")
        cnt = len(items)
        if cnt == last:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
            last = cnt
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", results)
        time.sleep(0.25)

    names = [i.text.strip() for i in items if i.text.strip()]
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    return names


def select_province(driver, name):
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "select2-province-selector-container"))
    ).click()
    search = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input.select2-search__field"))
    )
    search.clear()
    search.send_keys(name)
    time.sleep(0.35)
    xp = ("//li[contains(@class,'select2-results__option') and "
          "normalize-space(text())='{0}']").format(name)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xp)))
    js_click(driver, driver.find_element(By.XPATH, xp))
    WebDriverWait(driver, 12).until(lambda d: name in d.page_source)


def parse_today(driver, name):
    soup = BeautifulSoup(driver.page_source, "html.parser")
    for card in soup.find_all("div", class_="card card-shadow text-center"):
        head = card.find("div", class_="font-small")
        if not head or head.get_text(strip=True) != "วันนี้":
            continue
        date_txt = card.find("div", class_="font-tiny text-dark2").get_text(strip=True)
        temps = card.find("div", class_="d-flex justify-content-around sub-heading")
        dv = temps.find_all("div") if temps else []
        tmax = dv[0].get_text(strip=True) if len(dv) > 0 else ""
        tmin = dv[2].get_text(strip=True) if len(dv) > 2 else ""
        tinys = card.find_all("div", class_="font-tiny text-center")
        cond  = tinys[0].get_text(strip=True) if len(tinys) > 0 else ""
        rain  = tinys[1].get_text(strip=True) if len(tinys) > 1 else ""
        wind_el = card.find("span", class_="font-tiny ps-1")
        wind = wind_el.get_text(strip=True) if wind_el else ""
        return {
            "จังหวัด/รายการ": name,
            "วันที่": date_txt,
            "อุณหภูมิสูงสุด": tmax,
            "อุณหภูมิต่ำสุด": tmin,
            "สภาพอากาศ": cond,
            "โอกาสฝน": rain,
            "ลม": wind,
            "เวลาบันทึก": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    return None


def main():
    driver = make_driver()
    rows, failed = [], []
    try:
        open_home_ready(driver)
        names = collect_all_select2_items(driver)
        print(f"รายการจาก select2 ทั้งหมด: {len(names)} รายการ")

        for i, name in enumerate(names, 1):
            ok = False
            for attempt in range(2):
                try:
                    select_province(driver, name)
                    row = parse_today(driver, name)
                    if row:
                        rows.append(row); ok = True
                        print(f"[{i}/{len(names)}] {name} ✔")
                        break
                except Exception as e:
                    if attempt == 0:
                        try:
                            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        except:
                            pass
                        time.sleep(0.7)
                    else:
                        print(f"[{i}/{len(names)}] {name} ✖ {e}")
                time.sleep(random.uniform(0.3, 0.8))
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
