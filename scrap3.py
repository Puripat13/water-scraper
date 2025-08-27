# https://nationalthaiwater.onwr.go.th/dam ใช้เก็บข้อมูลแหล่งน้ำ

import os
import time
import base64
import json
import requests
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# =====================[ CONFIG | GitHub Upload ]=====================
GITHUB_UPLOAD   = os.environ.get("GITHUB_UPLOAD", "false").lower() == "true"
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")             # ต้องมีถ้า GITHUB_UPLOAD=true
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "Puripat13/water-scraper")
GITHUB_BRANCH   = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_DEST_DIR = os.environ.get("GITHUB_DEST_DIR", "").strip("/")  # e.g. "data" หรือว่าง = root
COMMIT_AUTHOR   = os.environ.get("GIT_AUTHOR", "github-actions[bot]")
COMMIT_EMAIL    = os.environ.get("GIT_EMAIL", "github-actions[bot]@users.noreply.github.com")

def _gh_api(path: str) -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

def upload_to_github(local_path: str, dest_path_in_repo: str, message: str):
    """
    อัปโหลด/อัปเดตไฟล์ลง GitHub Repo ผ่าน Contents API
    - สร้างไฟล์ใหม่ถ้ายังไม่มี
    - ถ้ามีอยู่แล้วจะอ่าน SHA แล้วทำการ update
    """
    if not os.path.exists(local_path):
        print(f"⚠️ ไม่พบไฟล์ {local_path} ข้ามการอัปโหลด")
        return

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
    url = _gh_api(dest_path_in_repo)

    # หา SHA เดิม (ถ้ามี) เพื่อ update
    sha = None
    get_res = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH})
    if get_res.status_code == 200:
        try:
            sha = get_res.json().get("sha")
        except Exception:
            sha = None

    payload = {
        "message": message,
        "content": content_b64,
        "branch": GITHUB_BRANCH,
        "committer": {"name": COMMIT_AUTHOR, "email": COMMIT_EMAIL},
    }
    if sha:
        payload["sha"] = sha

    put_res = requests.put(url, headers=headers, data=json.dumps(payload))
    if put_res.status_code in (200, 201):
        action = "อัปเดต" if sha else "สร้าง"
        print(f"✅ {action}ไฟล์ใน GitHub: {dest_path_in_repo}")
    else:
        print(f"❌ อัปโหลดล้มเหลว: {dest_path_in_repo} -> {put_res.status_code} {put_res.text}")

# =====================[ Scraper ]=====================
options = Options()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1366,840')

driver = webdriver.Chrome(options=options)
driver.get('https://nationalthaiwater.onwr.go.th/dam')

WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

start_time = time.time()  # 👉 เพิ่มก่อนเริ่ม scrape

def scrape_data(tab_name):
    all_data = []
    current_date = datetime.today().strftime("%d/%m/%Y")
    page = 1

    print(f"\nเริ่มดึงข้อมูล: {tab_name}")

    while True:
        time.sleep(2)
        rows = driver.find_elements(By.CSS_SELECTOR, ".MuiTable-root tbody tr")
        count_before = len(all_data)

        for row in rows:
            cols = [col.text.strip() for col in row.find_elements(By.CSS_SELECTOR, "td")]
            # ป้องกันแถวว่างจริง ๆ
            if any(col not in ("", "-", None) for col in cols):
                cols += [current_date, tab_name]
                all_data.append(cols)

        count_after = len(all_data)
        scraped_this_page = count_after - count_before
        print(f"หน้า {page}: เก็บข้อมูลแล้ว {scraped_this_page} แถว")

        try:
            next_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@title='Next Page']/button"))
            )
            if next_button.is_enabled():
                driver.execute_script("arguments[0].click();", next_button)
                page += 1
                print(f"ไปยังหน้า {page}...")
                time.sleep(2)
            else:
                print(f"จบการดึงข้อมูล: {tab_name}")
                break
        except:
            print(f"ไม่พบปุ่ม 'Next Page' หรือคลิกไม่ได้: {tab_name}")
            break

    return all_data

def save_data_to_csv(data, dam_type):
    if not data:
        print(f"⚠️ ไม่มีข้อมูลสำหรับ {dam_type} ไม่บันทึกไฟล์")
        return None

    file_path = f"waterdam_report_{dam_type}.csv"
    file_exists = os.path.exists(file_path)

    df = pd.DataFrame(data)

    # ลบคอลัมน์ที่ไม่มีข้อมูลเลย + ทำความสะอาดเบา ๆ
    df.replace("", pd.NA, inplace=True)
    df.dropna(axis=1, how='all', inplace=True)

    new_num_cols = df.shape[1]

    if file_exists:
        with open(file_path, encoding="utf-8-sig") as f:
            first_line = f.readline()
            existing_cols = len(first_line.strip().split(","))
        if existing_cols != new_num_cols:
            print(f"⚠️ โครงสร้างข้อมูลไม่ตรงกับไฟล์เดิม ({existing_cols} ≠ {new_num_cols}) ไม่บันทึก {dam_type}")
            return None

    df.to_csv(file_path, mode='a', index=False, encoding="utf-8-sig", header=not file_exists)
    print(f"💾 บันทึกข้อมูล {dam_type} ลงไฟล์ {file_path} แล้ว ({len(df)} แถว)")

    return file_path

# ========= ดึงแหล่งน้ำขนาดใหญ่ =========
large_dam_data = scrape_data("แหล่งน้ำขนาดใหญ่")

# ไปยังแท็บ 'แหล่งน้ำขนาดกลาง' อย่างปลอดภัย
medium_tab_button = WebDriverWait(driver, 15).until(
    EC.presence_of_element_located((By.XPATH, "//button[@aria-controls='tabpanel-1']"))
)

# รอให้ overlay (เช่น loading screen) หายไปก่อนคลิก
try:
    WebDriverWait(driver, 10).until_not(
        EC.presence_of_element_located((By.CLASS_NAME, "MuiBackdrop-root"))
    )
except:
    pass

# Scroll และคลิกปุ่มแบบปลอดภัย
driver.execute_script("arguments[0].scrollIntoView(true);", medium_tab_button)
time.sleep(1)
driver.execute_script("arguments[0].click();", medium_tab_button)

WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, ".MuiTable-root tbody tr"))
)

# ========= ดึงแหล่งน้ำขนาดกลาง =========
medium_dam_data = scrape_data("แหล่งน้ำขนาดกลาง")

# ========= บันทึก CSV =========
large_csv  = save_data_to_csv(large_dam_data, "large")
medium_csv = save_data_to_csv(medium_dam_data, "medium")

driver.quit()
end_time = time.time()  # 👉 หลัง quit()
print(f"⏱️ ใช้เวลาในการรันทั้งหมด: {end_time - start_time:.2f} วินาที")

# =====================[ อัปโหลดเข้า GitHub Repo ]=====================
if GITHUB_UPLOAD and GITHUB_TOKEN:
    dest_dir = f"{GITHUB_DEST_DIR}/" if GITHUB_DEST_DIR else ""
    if large_csv:
        upload_to_github(
            local_path=large_csv,
            dest_path_in_repo=f"{dest_dir}{os.path.basename(large_csv)}",
            message="Update dam water (large) CSV [skip ci]"
        )
    if medium_csv:
        upload_to_github(
            local_path=medium_csv,
            dest_path_in_repo=f"{dest_dir}{os.path.basename(medium_csv)}",
            message="Update dam water (medium) CSV [skip ci]"
        )
else:
    print("ℹ️ ข้ามการอัปโหลดไป GitHub (ตั้ง GITHUB_UPLOAD=true และใส่ GITHUB_TOKEN เพื่อเปิดใช้งาน)")
