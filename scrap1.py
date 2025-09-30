# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import time
import random
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# -------- Selenium --------
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)
from selenium.webdriver.chrome.service import Service

# ======================================================================
# CONFIG
# ======================================================================
HOME: str = os.getenv("TMD_HOME", "https://www.tmd.go.th")
CSV_OUT: str = os.getenv("CSV_OUT", r"tmd_7day_forecast_today.csv")

PAGELOAD_TIMEOUT: int = int(os.getenv("PAGELOAD_TIMEOUT", "50"))
SCRIPT_TIMEOUT: int   = int(os.getenv("SCRIPT_TIMEOUT", "50"))
WAIT_MED: int        = int(os.getenv("WAIT_MED", "20"))
WAIT_LONG: int       = int(os.getenv("WAIT_LONG", "35"))

RETRIES_PER_PROVINCE = int(os.getenv("RETRIES_PER_PROVINCE", "2"))
MAX_SCRAPE_PASSES    = int(os.getenv("MAX_SCRAPE_PASSES", "5"))

SLEEP_MIN = float(os.getenv("SLEEP_MIN", "0.7"))
SLEEP_MAX = float(os.getenv("SLEEP_MAX", "1.2"))

PAGE_LOAD_STRATEGY: str = os.getenv("PAGE_LOAD_STRATEGY", "none")
RE_INT = re.compile(r"(\d+)")

DEBUG_DIR = "_debug"

# ======================================================================
# DEBUG/WAIT HELPERS
# ======================================================================
def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def save_debug(driver, prefix: str) -> None:
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        tag = _now_tag()
        html_path = os.path.join(DEBUG_DIR, f"{prefix}_{tag}.html")
        png_path  = os.path.join(DEBUG_DIR, f"{prefix}_{tag}.png")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        try:
            driver.save_screenshot(png_path)
        except Exception:
            pass
        # console logs (ถ้าเปิด capability ไว้)
        try:
            logs = driver.get_log("browser")
            log_path = os.path.join(DEBUG_DIR, f"{prefix}_{tag}.log")
            with open(log_path, "w", encoding="utf-8") as f:
                for entry in logs:
                    lvl = entry.get("level", "?")
                    msg = entry.get("message", "")
                    f.write(f"[{lvl}] {msg}\n")
        except Exception:
            pass
        print(f"💾 Saved debug: {os.path.basename(html_path)}, {os.path.basename(png_path)}")
    except Exception:
        pass

def wait_dom_ready(driver, timeout=WAIT_LONG):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

def try_click_if_present(driver, css_list, timeout=5) -> Tuple[bool, Optional[str]]:
    for css in css_list:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.15)
            el.click()
            return True, css
        except Exception:
            continue
    return False, None

def find_first_present(driver, selectors, by="css", timeout=WAIT_LONG):
    for sel in selectors:
        try:
            if by == "css":
                el = WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
            else:
                el = WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.XPATH, sel))
                )
            return el, sel
        except Exception:
            continue
    raise TimeoutException(f"ไม่พบ element จาก selector ใด ๆ: {selectors}")

# ======================================================================
# SELENIUM HELPERS
# ======================================================================
def make_driver() -> webdriver.Chrome:
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1366,768")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--disable-features=IsolateOrigins,site-per-process")
    opt.add_argument("--lang=th-TH")
    opt.page_load_strategy = PAGE_LOAD_STRATEGY

    # เดิมคุณใช้ desired_capabilities=caps เพื่อเปิด console logs
    # ใน Selenium 4 ให้ย้ายมาใส่ใน options แบบนี้แทน:
    opt.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    # ไม่ต้องส่ง desired_capabilities อีกต่อไป
    drv = webdriver.Chrome(options=opt)  # ถ้าต้องระบุ service: webdriver.Chrome(service=Service(), options=opt)
    drv.set_page_load_timeout(PAGELOAD_TIMEOUT)
    drv.set_script_timeout(SCRIPT_TIMEOUT)
    return drv

def safe_get(driver, url, timeout=PAGELOAD_TIMEOUT):
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass

# ----------------------------------------------------------------------
# OPEN HOME (ทน cookie/iframe/selector แปรผัน)
# ----------------------------------------------------------------------
def open_home_ready(driver) -> None:
    attempts = 3
    for i in range(1, attempts + 1):
        try:
            print(f"🌐 เปิดหน้า: {HOME} (attempt {i}/{attempts})")
            safe_get(driver, HOME, timeout=WAIT_MED)
            wait_dom_ready(driver)

            # ปิด cookie/consent ถ้ามี
            clicked, which = try_click_if_present(
                driver,
                css_list=[
                    "#onetrust-accept-btn-handler",
                    "button[aria-label='Accept all']",
                    "button.cookie-accept",
                    ".ot-sdk-container #acceptBtn",
                ],
                timeout=3,
            )
            if clicked:
                print(f"✅ ปิด cookie banner ด้วย selector: {which}")

            # ถ้ามี iframe ตัวเดียว ให้สลับเข้าไป
            iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
            if len(iframes) == 1:
                try:
                    driver.switch_to.frame(iframes[0])
                    print("🔀 พบ 1 iframe: switched into it")
                except Exception:
                    pass
            _candidate_css = [
                "#province-selector",                          
                "select[name*='province' i]",
                "select[aria-label*='จังหวัด']",
                "select",
                # กรณีเป็น MUI/React Select
                "[role='button'][aria-haspopup='listbox']",
                ".MuiSelect-select",
                ".MuiAutocomplete-root input",
            ]
            el, used = find_first_present(driver, _candidate_css, by="css", timeout=WAIT_LONG)
            print(f"✅ พบคอนโทรลเลือกจังหวัดด้วย selector: {used}")

            # กลับออกจาก iframe ถ้าเคยเข้า
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return
        except TimeoutException as e:
            print(f"⏳ Timeout รอบที่ {i}: {e}")
            save_debug(driver, prefix=f"open_home_timeout_{i}")
            if i == attempts:
                raise
            try:
                driver.execute_script("location.reload(true);")
            except Exception:
                pass
            time.sleep(2)

# ----------------------------------------------------------------------
# READ MAPPING FROM CONTROL (รองรับทั้ง <select> และ MUI listbox)
# ----------------------------------------------------------------------
def collect_mapping_from_select(driver) -> Dict[str, str]:
    """
    คืนค่า mapping ชื่อจังหวัด -> โทเค็นค่าที่ใช้เลือก 2 แบบ:
      - 'VAL:<value>'  สำหรับ <select><option value=...>
      - 'TXT:<text>'   สำหรับ MUI listbox (เลือกตามข้อความ)
    """
    MAX_TRIES = 5
    mapping: Dict[str, str] = {}

    for attempt in range(1, MAX_TRIES + 1):
        # 1) ลองแบบ <select>
        try:
            sel = WebDriverWait(driver, WAIT_MED).until(
                EC.presence_of_element_located((By.ID, "province-selector"))
            )
            try:
                driver.execute_script("arguments[0].focus();", sel)
                driver.execute_script("arguments[0].click();", sel)
                time.sleep(0.2)
            except Exception:
                pass

            options = sel.find_elements(By.TAG_NAME, "option")
            local_map = {}
            for op in options:
                name = (op.text or "").strip()
                val = (op.get_attribute("value") or "").strip()
                if not name or not val:
                    continue
                if name.startswith("เลือก"):
                    continue
                local_map[name] = f"VAL:{val}"

            if len(local_map) >= 10:
                print(f"📋 อ่านจังหวัดจาก <select> ได้ {len(local_map)} รายการ")
                return local_map
        except Exception:
            pass

        # 2) ลองแบบ MUI: คลิกเปิด dropdown แล้วหา role=option
        try:
            # ตัวคุม dropdown
            dd, used = find_first_present(
                driver,
                selectors=[
                    "[role='button'][aria-haspopup='listbox']",
                    ".MuiSelect-select",
                    ".MuiAutocomplete-root input",
                ],
                by="css",
                timeout=WAIT_MED,
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dd)
            time.sleep(0.1)
            try:
                dd.click()
            except Exception:
                driver.execute_script("arguments[0].click();", dd)

            time.sleep(0.2)
            opts = driver.find_elements(By.CSS_SELECTOR, "[role='listbox'] [role='option']")
            local_map = {}
            for op in opts:
                name = (op.text or "").strip()
                if not name or name.startswith("เลือก"):
                    continue
                local_map[name] = f"TXT:{name}"

            if len(local_map) >= 10:
                print(f"📋 อ่านจังหวัดจาก MUI listbox ได้ {len(local_map)} รายการ")
                # ปิดเมนูถ้าเปิดอยู่ (กดอีกครั้ง)
                try:
                    dd.click()
                except Exception:
                    pass
                return local_map
        except Exception:
            pass

        time.sleep(0.5)
        try:
            driver.refresh()
        except Exception:
            pass
        time.sleep(0.5)

    raise TimeoutException("อ่านรายชื่อจังหวัดได้น้อยผิดปกติ")

# ----------------------------------------------------------------------
# SELECT PROVINCE (รองรับ 2 โหมด)
# ----------------------------------------------------------------------
def _js_set_select_value(driver, value: str) -> bool:
    js = """
    var s=document.getElementById('province-selector');
    if(!s) return false;
    s.value=arguments[0];
    s.dispatchEvent(new Event('change',{bubbles:true}));
    return true;
    """
    return bool(driver.execute_script(js, value))

def _open_mui_dropdown(driver) -> Optional[object]:
    try:
        dd, _ = find_first_present(
            driver,
            selectors=[
                "[role='button'][aria-haspopup='listbox']",
                ".MuiSelect-select",
                ".MuiAutocomplete-root input",
            ],
            by="css",
            timeout=WAIT_MED,
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dd)
        time.sleep(0.1)
        try:
            dd.click()
        except Exception:
            driver.execute_script("arguments[0].click();", dd)
        return dd
    except Exception:
        return None

def _mui_click_option_by_text(driver, text_want: str) -> bool:
    # สมมติข้อความตรงตัว (ignore-case)
    opts = driver.find_elements(By.CSS_SELECTOR, "[role='listbox'] [role='option']")
    text_want_norm = (text_want or "").strip().lower()
    for op in opts:
        t = (op.text or "").strip().lower()
        if t == text_want_norm:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", op)
            time.sleep(0.05)
            try:
                op.click()
            except Exception:
                driver.execute_script("arguments[0].click();", op)
            return True
    return False

def select_province(driver, province_name: str, mapping: Dict[str, str]) -> bool:
    token = mapping.get(province_name, "")
    if not token:
        return False

    if token.startswith("VAL:"):
        val = token.split(":", 1)[1]
        ok = _js_set_select_value(driver, val)
        if ok:
            time.sleep(0.2)
        return ok

    if token.startswith("TXT:"):
        want_text = token.split(":", 1)[1]
        dd = _open_mui_dropdown(driver)
        if not dd:
            return False
        ok = _mui_click_option_by_text(driver, want_text)
        if not ok:
            # เผื่อ listbox ถูกปิด ให้ลองเปิดใหม่อีกครั้ง
            dd = _open_mui_dropdown(driver)
            if dd:
                ok = _mui_click_option_by_text(driver, want_text)
        if ok:
            time.sleep(0.2)
        return ok

    return False

# ----------------------------------------------------------------------
# SCRAPE "TODAY"
# ----------------------------------------------------------------------
def wait_rain_info(driver):
    WebDriverWait(driver, WAIT_MED).until(
        EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'%')]"))
    )

def _extract_percent(text: str) -> Optional[float]:
    m = RE_INT.search(text or "")
    return (int(m.group(1)) / 100.0) if m else None

def parse_today_fast(driver, province_name: str) -> Optional[Dict[str, str]]:
    cards = driver.find_elements(By.CSS_SELECTOR, "div.card.card-shadow.text-center")
    for c in cards:
        try:
            head = c.find_element(By.CSS_SELECTOR, "div.font-small")
            if head.text.strip() != "วันนี้":
                continue
            tiny = c.find_elements(By.CSS_SELECTOR, "div.font-tiny.text-center")
            cond, rain_text = None, None
            for el in tiny:
                txt = (el.text or "").strip()
                if "%" in txt and not rain_text:
                    rain_text = txt
                elif "%" not in txt and not cond:
                    cond = txt
            if cond and rain_text:
                return {
                    "Province": province_name,
                    "Weather": cond,
                    "RainChance": _extract_percent(rain_text),
                    "DateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
        except Exception:
            continue
    return None

# ======================================================================
# MAIN
# ======================================================================
def main():
    driver = make_driver()
    all_rows: List[Dict[str, str]] = []
    failed: List[str] = []

    try:
        # เปิดหน้า + กันพลาดด้วย retry ภายในฟังก์ชัน
        open_home_ready(driver)

        mapping = collect_mapping_from_select(driver)
        names = list(mapping.keys())
        print(f"พบจังหวัด {len(names)} รายการ")

        to_try = names[:]
        pass_num = 0
        prev_failed_count: Optional[int] = None

        while to_try and pass_num < MAX_SCRAPE_PASSES:
            pass_num += 1
            print(f"\nเริ่มรอบที่ {pass_num} (ลอง {len(to_try)} จังหวัด)")
            rows, failed_this = _try_scrape_provinces(
                driver, to_try, RETRIES_PER_PROVINCE, mapping
            )

            all_rows.extend(rows)
            print(f"รอบ {pass_num} สำเร็จ {len(rows)} จังหวัด, พลาด {len(failed_this)} จังหวัด")

            if not failed_this:
                print("✅ เก็บข้อมูลครบทุกจังหวัดแล้ว")
                failed = []
                break

            if prev_failed_count is not None and len(failed_this) >= prev_failed_count:
                print("⚠️ ไม่มีความคืบหน้าจากรอบก่อนหน้า")
                failed = failed_this
                break

            to_try = failed_this
            prev_failed_count = len(failed_this)

        else:
            failed = to_try if to_try else []

    finally:
        driver.quit()

    new_df = pd.DataFrame(all_rows)

    # Save only to local CSV file
    if not new_df.empty:
        out_dir = os.path.dirname(os.path.abspath(CSV_OUT))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        new_df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
        print(f"\n📝 บันทึกแถวใหม่ลงโลคอล: {CSV_OUT}")
    else:
        print("\n❌ ไม่พบข้อมูลใหม่ที่ scrape ได้")

# ======================================================================
# INTERNAL: scrape loop
# ======================================================================
def _try_scrape_provinces(
    driver,
    names: List[str],
    retries_per_province: int,
    mapping: Dict[str, str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    rows: List[Dict[str, str]] = []
    failed: List[str] = []
    total = len(names)
    print(f"เริ่มดึง {total} จังหวัด")

    for i, name in enumerate(names, 1):
        ok = False
        for attempt in range(retries_per_province):
            try:
                if not select_province(driver, name, mapping):
                    raise RuntimeError("ตั้งค่า select ไม่สำเร็จ")

                WebDriverWait(driver, WAIT_MED).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.card.card-shadow.text-center"))
                )
                wait_rain_info(driver)

                row = parse_today_fast(driver, name)
                if row:
                    rows.append(row)
                    ok = True
                    print(f"[{i}/{total}] {name} ✔")
                    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))
                    break
                else:
                    raise RuntimeError("อ่าน card วันนี้ ไม่สำเร็จ")

            except (StaleElementReferenceException, TimeoutException) as e:
                if attempt == retries_per_province - 1:
                    save_debug(driver, prefix=f"province_fail_{i}_{name}")
                try:
                    driver.refresh()
                except Exception:
                    pass
                time.sleep(0.8)
            except Exception as e:
                if attempt < retries_per_province - 1:
                    try:
                        driver.refresh()
                    except Exception:
                        pass
                    time.sleep(0.8)
                else:
                    print(f"[{i}/{total}] {name} ✖ {e}")

        if not ok:
            failed.append(name)

    return rows, failed

# ======================================================================
# ENTRY
# ======================================================================
if __name__ == "__main__":
    main()
