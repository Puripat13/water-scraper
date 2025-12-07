# -*- coding: utf-8 -*-
import os
import time
import json
import random
import requests
from datetime import datetime
from typing import Dict, List

import pandas as pd

# ---- Selenium ----
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# ---- Google Drive API ----
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from io import BytesIO, StringIO


# ============================================================
# CONFIG
# ============================================================
HOME = "https://www.tmd.go.th"

CSV_OUT = os.getenv("CSV_OUT", "tmd_7day_forecast_today.csv")
ENABLE_GOOGLE_DRIVE_UPLOAD = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "false") == "true"
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
DRIVE_FILE_ID = os.getenv("DRIVE_FILE_ID")

WAIT_LONG = 25
WAIT_MED = 15
SLEEP_MIN = 0.6
SLEEP_MAX = 1.0


# ============================================================
# Bypass popup
# ============================================================
def bypass_popup(driver):
    js = """
    try {
        localStorage.setItem('eventVisited','true');
        document.cookie = 'eventVisited=true; path=/; SameSite=Lax';

        document.querySelectorAll('button').forEach(b=>{
            if (b.innerText.includes('เข้าสู่เว็บไซต์')) b.click();
        });

        ['.modal','.modal-backdrop','.swal2-container','[id*=overlay]','[class*=overlay]']
        .forEach(sel => document.querySelectorAll(sel).forEach(el=>el.remove()));

        document.body.style.overflow = 'auto';
    } catch(e){}
    """
    driver.execute_script(js)


# ============================================================
# Selenium driver
# ============================================================
def make_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=opt)

def safe_get(driver, url):
    try:
        driver.get(url)
    except:
        driver.execute_script("window.stop();")


# ============================================================
# จังหวัด จาก API (แทน DOM เดิม)
# ============================================================
def collect_mapping() -> Dict[str, str]:
    url = "https://www.tmd.go.th/api/province/select"
    r = requests.get(url, timeout=10)
    data = r.json()

    mapping = {item["text"]: item["value"] for item in data if item.get("text")}
    if len(mapping) < 70:
        raise TimeoutException("โหลดจังหวัดไม่ครบจาก API")

    print(f"✔ โหลดจังหวัด {len(mapping)} รายการ จาก API แล้ว")
    return mapping


# ============================================================
# Google Drive upload
# ============================================================
def build_drive():
    info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def drive_read_df(service):
    req = service.files().get_media(fileId=DRIVE_FILE_ID)
    data = req.execute()

    text = data.decode("utf-8-sig")
    return pd.read_csv(StringIO(text))

def drive_merge_update(df_new: pd.DataFrame):
    service = build_drive()

    try:
        df_old = drive_read_df(service)
    except:
        df_old = pd.DataFrame()

    all_cols = list({*df_old.columns, *df_new.columns})
    df_old = df_old.reindex(columns=all_cols)
    df_new = df_new.reindex(columns=all_cols)

    merged = pd.concat([df_old, df_new], ignore_index=True)
    merged.drop_duplicates(subset=["Province", "DateTime"], keep="last", inplace=True)

    buf = BytesIO()
    buf.write(merged.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"))
    buf.seek(0)

    media = MediaIoBaseUpload(buf, mimetype="text/csv")
    service.files().update(
        fileId=DRIVE_FILE_ID,
        media_body=media,
        supportsAllDrives=True
    ).execute()

    print(f"✔ อัปเดตไฟล์ Drive rows = {len(merged)}")
    return len(merged)


# ============================================================
# Scraper
# ============================================================
def open_home(driver):
    safe_get(driver, HOME)
    time.sleep(2)
    bypass_popup(driver)
    time.sleep(2)

def select_province(driver, mapping, name):
    val = mapping[name]
    js = """
    var s = document.getElementById('province-selector');
    s.value = arguments[0];
    s.dispatchEvent(new Event('change',{bubbles:true}));
    """
    driver.execute_script(js, val)
    time.sleep(0.5)

def wait_forecast(driver):
    WebDriverWait(driver, WAIT_LONG).until(
        EC.any_of(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".forecast-rain")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'%')]"))
        )
    )

def parse(driver, province):
    rain = driver.find_elements(By.CSS_SELECTOR, ".forecast-rain")
    weather = driver.find_elements(By.CSS_SELECTOR, ".forecast-weather")

    return {
        "Province": province,
        "Weather": weather[0].text if weather else None,
        "RainChance": None,
        "Rainfall_mm": None,
        "DateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ============================================================
# MAIN
# ============================================================
def main():
    driver = make_driver()
    rows = []

    try:
        open_home(driver)
        mapping = collect_mapping()

        for i, prov in enumerate(mapping.keys(), 1):
            try:
                select_province(driver, mapping, prov)
                wait_forecast(driver)
                row = parse(driver, prov)
                rows.append(row)
                print(f"[{i}] {prov} ✔")
                time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))
            except Exception as e:
                print(f"[{i}] {prov} ✖ {e}")

    finally:
        driver.quit()

    df = pd.DataFrame(rows)
    df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"✔ บันทึก CSV → {CSV_OUT}")

    if ENABLE_GOOGLE_DRIVE_UPLOAD:
        drive_merge_update(df)


if __name__ == "__main__":
    main()
