# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import time
import json
import random
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# -------- Selenium --------
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException

# -------- Google Drive API (Service Account) --------
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from io import BytesIO, StringIO

# ======================================================================
# CONFIG
# ======================================================================
HOME: str = os.getenv("TMD_HOME", "https://www.tmd.go.th")
CSV_OUT: str = os.getenv("CSV_OUT", "tmd_7day_forecast_today.csv")

ENABLE_GOOGLE_DRIVE_UPLOAD: bool = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "true").lower() == "true"
SERVICE_ACCOUNT_JSON: Optional[str] = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_FILE: str = os.getenv(
    "SERVICE_ACCOUNT_FILE",
    r"C:\Project_End\CodeProject\githubproject-467507-653192ee67bf.json",
)

# 🔒 ใช้ fileId เดิมแบบบังคับ (แก้เป็น id ของไฟล์ปลายทางของคุณ)
DRIVE_FILE_ID: Optional[str] = os.getenv("DRIVE_FILE_ID")
CSV_MIMETYPE: str = "text/csv"

PAGELOAD_TIMEOUT: int = int(os.getenv("PAGELOAD_TIMEOUT", "50"))
SCRIPT_TIMEOUT: int = int(os.getenv("SCRIPT_TIMEOUT", "50"))
WAIT_MED: int = int(os.getenv("WAIT_MED", "20"))
WAIT_LONG: int = int(os.getenv("WAIT_LONG", "35"))

RETRIES_PER_PROVINCE = int(os.getenv("RETRIES_PER_PROVINCE", "2"))
MAX_SCRAPE_PASSES = int(os.getenv("MAX_SCRAPE_PASSES", "5"))

SLEEP_MIN = float(os.getenv("SLEEP_MIN", "0.7"))
SLEEP_MAX = float(os.getenv("SLEEP_MAX", "1.2"))

PAGE_LOAD_STRATEGY: str = os.getenv("PAGE_LOAD_STRATEGY", "none")

RE_INT = re.compile(r"(\d+)")
RE_MM = re.compile(r"([\d\.,]+)\s*มม\.?")

# ================= Email Notify (SMTP) =================
EMAIL_ENABLED: bool = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
EMAIL_SENDER: str = os.getenv("EMAIL_SENDER", "pph656512@gmail.com")
EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "nfns uuan ayrx uykm")  # ⚠️ แนะนำส่งผ่าน ENV จริง
EMAIL_TO: str = os.getenv("EMAIL_TO", "pph656512@gmail.com")


def send_email(subject: str, body_text: str) -> None:
    if not EMAIL_ENABLED:
        return
    try:
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        import smtplib

        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, [x.strip() for x in EMAIL_TO.split(",")], msg.as_string())
        server.quit()
        print("📧 ส่งอีเมลแจ้งเตือนแล้ว")
    except Exception as e:
        print("⚠️ ส่งอีเมลล้มเหลว:", e)


# ======================================================================
# GOOGLE DRIVE HELPERS (Update-only)
# ======================================================================
def _check_prereq() -> None:
    if not ENABLE_GOOGLE_DRIVE_UPLOAD:
        return
    if not (SERVICE_ACCOUNT_JSON or (SERVICE_ACCOUNT_FILE and os.path.exists(SERVICE_ACCOUNT_FILE))):
        raise FileNotFoundError("ไม่พบ Service Account (ตั้ง SERVICE_ACCOUNT_JSON หรือ SERVICE_ACCOUNT_FILE)")
    if not DRIVE_FILE_ID:
        raise RuntimeError("ต้องตั้ง DRIVE_FILE_ID เป็น fileId ของไฟล์ปลายทางเพื่ออัปเดตลิงก์เดิม")


def build_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    if SERVICE_ACCOUNT_JSON:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(SERVICE_ACCOUNT_JSON), scopes=scopes
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=scopes
        )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def drive_read_csv_as_df(service, file_id: str) -> Optional[pd.DataFrame]:
    try:
        req = service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        content = fh.read()
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")
        return pd.read_csv(StringIO(text))
    except HttpError as e:
        print(f"⚠️ อ่านไฟล์จาก Drive ไม่สำเร็จ: {e}")
        return None
    except Exception as e:
        print(f"⚠️ อ่าน CSV เป็น DataFrame ไม่สำเร็จ: {e}")
        return None


def drive_merge_and_update_df_update_only(
    df_new: pd.DataFrame,
    key_cols: Tuple[str, ...] = ("Province", "DateTime"),
    keep: str = "last",
    local_out_path: Optional[str] = None,
) -> Tuple[str, str, int]:
    """รวม df_new กับไฟล์เดิมบน Drive (DRIVE_FILE_ID) แล้ว 'update' กลับไฟล์เดิมเท่านั้น"""
    _check_prereq()
    service = build_drive_service()
    # ตรวจสิทธิ์ไฟล์เดิม
    service.files().get(fileId=DRIVE_FILE_ID, fields="id,name").execute()

    df_old = drive_read_csv_as_df(service, DRIVE_FILE_ID)

    # ✅ ใช้ union ของคอลัมน์ (ไม่ทิ้งคอลัมน์ใหม่ เช่น Rainfall_mm)
    if df_old is not None and len(df_old) > 0:
        all_cols = list({*df_old.columns.tolist(), *df_new.columns.tolist()})
        df_merged = pd.concat(
            [df_old.reindex(columns=all_cols), df_new.reindex(columns=all_cols)],
            ignore_index=True,
        )
    else:
        df_merged = df_new.copy()

    # ลบแถวซ้ำตาม key
    effective_keys = [c for c in key_cols if c in df_merged.columns]
    if effective_keys:
        df_merged = df_merged.drop_duplicates(subset=effective_keys, keep=keep)
    else:
        df_merged = df_merged.drop_duplicates(keep=keep)

    # บันทึกโลคอล (ออปชัน)
    if local_out_path:
        out_dir = os.path.dirname(os.path.abspath(local_out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        df_merged.to_csv(local_out_path, index=False, encoding="utf-8-sig")

    # อัปเดตไฟล์เดิมเท่านั้น
    buf = BytesIO()
    csv_bytes = df_merged.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    buf.write(csv_bytes)
    buf.seek(0)

    media = MediaIoBaseUpload(buf, mimetype=CSV_MIMETYPE, resumable=True)
    updated = service.files().update(
        fileId=DRIVE_FILE_ID,
        media_body=media,
        supportsAllDrives=True,
    ).execute()

    return "update", updated["id"], len(df_merged)


# ======================================================================
# SELENIUM HELPERS
# ======================================================================
def make_driver() -> webdriver.Chrome:
    opt = Options()
    opt.add_argument("--headless=new")  # เปิดถ้าต้องการ headless
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1366,768")
    opt.page_load_strategy = PAGE_LOAD_STRATEGY
    drv = webdriver.Chrome(options=opt)
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


# ===================== NEW: ENTRY-GATE / SPLASH DISMISSER =====================
def _try_click_entry_button_in_context(ctx) -> bool:
    """พยายามคลิกปุ่ม 'เข้าสู่เว็บไซต์' ใน context (driver หรือ iframe)"""
    try:
        btns = []
        btns += ctx.find_elements(By.CSS_SELECTOR, "button[onclick*='getEventVisited']")
        btns += ctx.find_elements(By.XPATH, "//button[contains(normalize-space(.), 'เข้าสู่เว็บไซต์')]")
        btns += ctx.find_elements(By.CSS_SELECTOR, "button.btn-primary-outline.btn.mt-2")
        for b in btns:
            try:
                ctx.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
            except Exception:
                pass
            try:
                ctx.execute_script("arguments[0].click();", b)
                time.sleep(0.35)
                return True
            except Exception:
                try:
                    b.click()
                    time.sleep(0.35)
                    return True
                except (ElementClickInterceptedException, Exception):
                    continue
    except Exception:
        pass
    return False


def _set_event_visited_via_js(driver) -> None:
    js = r"""
    try {
      if (typeof getEventVisited === 'function') { try { getEventVisited(); } catch(e) {} }
      localStorage.setItem('eventVisited', 'true');
      document.cookie = 'eventVisited=true; path=/; SameSite=Lax';
      var sel = [
        '.modal-backdrop','div.modal.show','div.modal.fade.show',
        '.swal2-container','[class*="overlay"]','[id*="overlay"]',
        '.swal2-shown','body.swal2-shown','[role="dialog"]'
      ];
      sel.forEach(s => document.querySelectorAll(s).forEach(el => {
        el.style.setProperty('display','none','important');
        el.style.setProperty('visibility','hidden','important');
        el.style.setProperty('opacity','0','important');
        el.classList.add('hidden');
      }));
      document.body.style.overflow = 'auto';
    } catch(e) {}
    """
    try:
        driver.execute_script(js)
    except Exception:
        pass


def _dismiss_entry_gate(driver, max_wait: int = 8) -> None:
    t0 = time.time()
    while time.time() - t0 < max_wait:
        if _try_click_entry_button_in_context(driver):
            time.sleep(0.5)
            break
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for f in iframes:
                try:
                    driver.switch_to.frame(f)
                    if _try_click_entry_button_in_context(driver):
                        driver.switch_to.default_content()
                        time.sleep(0.5)
                        return
                except Exception:
                    pass
                finally:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(0.3)

    _set_event_visited_via_js(driver)


# ===================== END ENTRY-GATE HANDLER =====================

def open_home_ready(driver) -> None:
    safe_get(driver, HOME, timeout=WAIT_MED)
    _dismiss_entry_gate(driver, max_wait=8)
    WebDriverWait(driver, WAIT_LONG).until(
        EC.presence_of_element_located((By.ID, "province-selector"))
    )


def collect_mapping_from_select(driver) -> Dict[str, str]:
    """
    รอให้ options ของ #province-selector โหลดครบ (≥70 รายการ) แล้วค่อยอ่าน
    """
    MAX_TRIES = 5
    mapping: Dict[str, str] = {}

    for attempt in range(1, MAX_TRIES + 1):
        sel = WebDriverWait(driver, WAIT_MED).until(
            EC.presence_of_element_located((By.ID, "province-selector"))
        )

        # รอจำนวน option ≥ 70
        try:
            WebDriverWait(driver, WAIT_LONG).until(
                lambda d: len(sel.find_elements(By.TAG_NAME, "option")) >= 70
            )
        except TimeoutException:
            # รีเฟรชแล้วลองใหม่
            driver.refresh()
            time.sleep(0.8)
            continue

        try:
            options = sel.find_elements(By.TAG_NAME, "option")
            for op in options:
                name = (op.text or "").strip()
                val  = (op.get_attribute("value") or "").strip()
                if not name or not val:
                    continue
                if name.startswith("เลือก"):
                    continue
                mapping[name] = val
        except StaleElementReferenceException:
            mapping = {}

        if len(mapping) >= 70:
            print(f"พบจังหวัด {len(mapping)} รายการ")
            return mapping

        time.sleep(0.5)
        driver.refresh()
        time.sleep(0.8)

    # ถ้ายังไม่ถึง 70 รายการ ให้ throw พร้อมตัวอย่าง
    sample = ", ".join(list(mapping.keys())[:3]) if mapping else "-"
    raise TimeoutException(f"อ่านรายชื่อจังหวัดได้น้อยผิดปกติ (count={len(mapping)}) ตัวอย่าง: {sample}")


def _js_set_select_value(driver, value: str) -> bool:
    js = """
    var s=document.getElementById('province-selector');
    if(!s) return false;
    s.value=arguments[0];
    s.dispatchEvent(new Event('change',{bubbles:true}));
    return true;
    """
    try:
        return bool(driver.execute_script(js, value))
    except Exception:
        return False


def select_province(driver, province_name: str, mapping: Dict[str, str]) -> bool:
    val = mapping.get(province_name, "")
    if not val:
        return False
    ok = _js_set_select_value(driver, val)
    if ok:
        time.sleep(0.3)
    return ok


def wait_rain_info(driver):
    """
    รอให้มีอย่างน้อยหนึ่งในข้อมูลฝนวันนี้ปรากฏ:
    - ข้อความมี '%' (โอกาสฝน)
    - .forecast-rain (ตาม DOM ใหม่)
    """
    WebDriverWait(driver, WAIT_LONG).until(
        EC.any_of(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'%')]")),
            EC.presence_of_element_located((By.CSS_SELECTOR, ".forecast-rain"))
        )
    )


def _extract_percent(text: str) -> Optional[float]:
    m = RE_INT.search(text or "")
    return (int(m.group(1)) / 100.0) if m else None


def _extract_mm(text: str) -> Optional[float]:
    m = RE_MM.search(text or "")
    if not m:
        return None
    try:
        # แทนที่ , เป็น . เผื่อรูปแบบ 1,2
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def parse_today_fast(driver, province_name: str) -> Optional[Dict[str, str]]:
    """
    ดึง: สภาพอากาศ (Weather), โอกาสฝน (RainChance 0-1), ฝนสะสมวันนี้ (Rainfall_mm)
    รองรับทั้ง DOM เก่าและใหม่
    """
    weather_text, rain_text, rainfall_val = None, None, None

    try:
        # 1) DOM ใหม่: คำอธิบายสภาพอากาศ
        el_weather = driver.find_elements(By.CSS_SELECTOR, ".forecast-weather")
        if el_weather:
            wt = (el_weather[0].text or "").strip()
            if wt:
                weather_text = wt

        # 2) DOM ใหม่: โอกาสฝน
        el_rain = driver.find_elements(By.CSS_SELECTOR, ".forecast-rain")
        if el_rain:
            rt = (el_rain[0].text or "").strip()
            if rt:
                rain_text = rt

        # 3) ฝนสะสมวันนี้
        #   3.1 ถ้ามี element id เดิม
        try:
            rainfall_el = driver.find_element(By.ID, "awsRainFrom7Am")
            t = (rainfall_el.text or "").strip()
            rainfall_val = float(t) if t else None
        except Exception:
            #   3.2 หาใน text: "ฝนสะสมวันนี้ X มม."
            el_acc = driver.find_elements(By.XPATH, "//*[contains(text(),'ฝนสะสมวันนี้')]")
            for el in el_acc:
                mm = _extract_mm(el.text or "")
                if mm is not None:
                    rainfall_val = mm
                    break

        # 4) Fallback DOM เก่า: มองหา card "วันนี้"
        if weather_text is None or rain_text is None:
            cards = driver.find_elements(By.CSS_SELECTOR, "div.card.card-shadow.text-center")
            for c in cards:
                try:
                    head = c.find_element(By.CSS_SELECTOR, "div.font-small")
                    if head.text.strip() != "วันนี้":
                        continue
                    tiny = c.find_elements(By.CSS_SELECTOR, "div.font-tiny.text-center")
                    for el in tiny:
                        txt = (el.text or "").strip()
                        if "%" in txt and rain_text is None:
                            rain_text = txt
                        elif "%" not in txt and weather_text is None:
                            weather_text = txt
                    if weather_text and rain_text:
                        break
                except Exception:
                    continue

        if weather_text and (rain_text or rainfall_val is not None):
            return {
                "Province": province_name,
                "Weather": weather_text,
                "RainChance": _extract_percent(rain_text) if rain_text else None,
                "Rainfall_mm": rainfall_val,
                "DateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
    except Exception as e:
        print("parse_today_fast error:", e)

    return None


# ======================================================================
# MAIN
# ======================================================================
def main():
    driver = make_driver()
    all_rows: List[Dict[str, str]] = []
    failed: List[str] = []
    try:
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
            rows, failed_this = _try_scrape_provinces(driver, to_try, RETRIES_PER_PROVINCE, mapping)
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

    action, fid, merged_rows = "-", "-", 0
    if ENABLE_GOOGLE_DRIVE_UPLOAD and not new_df.empty:
        try:
            action, fid, merged_rows = drive_merge_and_update_df_update_only(
                new_df,
                key_cols=("Province", "DateTime"),
                keep="last",
                local_out_path=CSV_OUT
            )
            print(f"\n✅ อัปเดตไฟล์เดิมสำเร็จ (id={fid}), total rows after merge: {merged_rows}")
        except Exception as e:
            print("⚠️ Drive update fail:", e)
    else:
        if not new_df.empty:
            out_dir = os.path.dirname(os.path.abspath(CSV_OUT))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            new_df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
            print(f"\n📝 บันทึกเฉพาะแถวใหม่ลงโลคอล: {CSV_OUT}")

    subject = f"[TMD Scraper] OK={len(all_rows)} FAIL={len(failed)}"
    body = (
        f"เพิ่มใหม่ (ก่อน merge): {len(all_rows)} แถว\n"
        f"รวมแล้วทั้งหมด (หลัง merge): {merged_rows or 0}\n"
        f"Drive: {action} id={fid}\n"
        f"Fail: {', '.join(failed) if failed else '-'}"
    )
    send_email(subject, body)


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

                # รอให้ข้อมูลส่วนการพยากรณ์โผล่
                WebDriverWait(driver, WAIT_MED).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
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
            except (StaleElementReferenceException, TimeoutException):
                driver.refresh()
                time.sleep(0.9)
            except Exception as e:
                if attempt < retries_per_province - 1:
                    driver.refresh()
                    time.sleep(0.9)
                else:
                    print(f"[{i}/{total}] {name} ✖ {e}")

        if not ok:
            failed.append(name)

    return rows, failed


# ======================================================================
# ENTRY
# ======================================================================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"[TMD Scraper] FAILED @ {when}"
        body = f"สคริปต์ล้มเหลวเมื่อ {when}\n\nError:\n{repr(e)}"
        send_email(subject, body)
        raise
