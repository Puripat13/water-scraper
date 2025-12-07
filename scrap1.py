# -*- coding: utf-8 -*-
import os
import time
import json
import random
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from io import BytesIO, StringIO

# =====================================================
# CONFIG
# =====================================================
HOME = "https://www.tmd.go.th"

CSV_OUT = os.getenv("CSV_OUT", "tmd_7day_forecast_today.csv")
ENABLE_GOOGLE_DRIVE_UPLOAD = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "false") == "true"

SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
DRIVE_FILE_ID = os.getenv("DRIVE_FILE_ID")  # ← ต้องเป็น FILE ID

WAIT_MED = 20
WAIT_LONG = 35
SLEEP_MIN = 0.7
SLEEP_MAX = 1.2

# =====================================================
# POPUP BYPASS (สำคัญสุด)
# =====================================================
def bypass_popup(driver):
    js = """
    try {
        localStorage.setItem('eventVisited','true');
        document.cookie = 'eventVisited=true; path=/; SameSite=Lax';
        document.querySelectorAll('button').forEach(b=>{
            if (b.innerText.includes('เข้าสู่เว็บไซต์')) b.click();
        });
        ['.modal','.modal-backdrop','.swal2-container','[id*=overlay]','[class*=overlay]']
        .forEach(sel => document.querySelectorAll(sel).forEach(e=>e.remove()));
        document.body.style.overflow = 'auto';
    } catch(e){}
    """
    driver.execute_script(js)

# =====================================================
# DRIVER
# =====================================================
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
    except Exception:
        driver.execute_script("window.stop();")

# =====================================================
# GOOGLE DRIVE
# =====================================================
def build_drive():
    info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def drive_read_df(service):
    req = service.files().get_media(fileId=DRIVE_FILE_ID)
    buf = BytesIO(req.execute())
    text = buf.read().decode("utf-8-sig")
    return pd.read_csv(StringIO(text))

def drive_merge_and_update(df_new: pd.DataFrame):
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

    csv_bytes = merged.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    buf = BytesIO(csv_bytes)
    buf.seek(0)

    media = MediaIoBaseUpload(buf, mimetype="text/csv")
    service.files().update(
        fileId=DRIVE_FILE_ID, media_body=media, supportsAllDrives=True
    ).execute()

    return len(merged)

# =====================================================
# SCRAPER
# =====================================================
def open_home(driver):
    safe_get(driver, HOME)
    time.sleep(2)
    bypass_popup(driver)
    time.sleep(2)
    WebDriverWait(driver, WAIT_LONG).until(
        EC.presence_of_element_located((By.ID, "province-selector"))
    )

def collect_mapping(driver) -> Dict[str, str]:
    WebDriverWait(driver, WAIT_LONG).until(
        EC.presence_of_element_located((By.ID, "province-selector"))
    )
    sel = driver.find_element(By.ID, "province-selector")
    opts = sel.find_elements(By.TAG_NAME, "option")

    mapping = {}
    for op in opts:
        t = op.text.strip()
        v = op.get_attribute("value").strip()
        if t and v and "เลือก" not in t:
            mapping[t] = v

    if len(mapping) < 70:
        raise TimeoutException("โหลดรายชื่อจังหวัดไม่ครบ")

    return mapping

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
    rain_el = driver.find_elements(By.CSS_SELECTOR, ".forecast-rain")
    weather_el = driver.find_elements(By.CSS_SELECTOR, ".forecast-weather")

    rain_text = rain_el[0].text if rain_el else None
    weather_text = weather_el[0].text if weather_el else None

    return {
        "Province": province,
        "Weather": weather_text,
        "RainChance": None,
        "Rainfall_mm": None,
        "DateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# =====================================================
# MAIN
# =====================================================
def main():
    driver = make_driver()
    rows = []

    try:
        open_home(driver)
        mapping = collect_mapping(driver)

        for i, prov in enumerate(mapping.keys(), 1):
            try:
                select_province(driver, mapping, prov)
                wait_forecast(driver)
                row = parse(driver, prov)
                rows.append(row)
                print(f"[{i}] {prov} ✔")
                time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))
            except Exception as e:
                print(f"{prov} ✖ {e}")

    finally:
        driver.quit()

    df = pd.DataFrame(rows)

    # ALWAYS save local CSV
    df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"Saved local CSV → {CSV_OUT}")

    if ENABLE_GOOGLE_DRIVE_UPLOAD:
        total = drive_merge_and_update(df)
        print(f"Updated Google Drive rows = {total}")

if __name__ == "__main__":
    main()
