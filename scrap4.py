# -*- coding: utf-8 -*-
import os, time, sys
import pandas as pd
from pathlib import Path
from datetime import datetime

# ============================== PATH SETUP ==============================
def _pick_existing(*candidates: Path) -> Path | None:
    for p in candidates:
        if p and Path(p).expanduser().resolve().exists():
            return Path(p).expanduser().resolve()
    return None

# โฟลเดอร์ฐาน:
# - บน GitHub Actions จะมี GITHUB_WORKSPACE
# - ถ้าไม่มี ให้ใช้โฟลเดอร์เดียวกับสคริปต์
BASE_DIR = Path(os.getenv("GITHUB_WORKSPACE", Path(__file__).parent)).resolve()

# ค่าจาก Environment (ถ้าไม่ใส่จะเป็นไฟล์ในโฟลเดอร์เดียวกับสคริปต์)
ENV_LARGE  = os.getenv("LARGE_CSV",  str(BASE_DIR / "waterdam_report_large.csv"))
ENV_MEDIUM = os.getenv("MEDIUM_CSV", str(BASE_DIR / "waterdam_report_medium.csv"))
ENV_OUT    = os.getenv("OUT_CSV",    str(BASE_DIR / "waterdam_report.csv"))

# รองรับ path เดิมที่เป็น Windows (ถ้าเผลอใส่มา)
WIN_LARGE  = r"C:\Project_End\CodeProject\waterdam_report_large.csv"
WIN_MEDIUM = r"C:\Project_End\CodeProject\waterdam_report_medium.csv"
WIN_OUT    = r"C:\Project_End\CodeProject\waterdam_report.csv"

# เลือกไฟล์ที่ "มีอยู่จริง" โดยไล่ลำดับความสำคัญ: ENV -> ไฟล์ข้างสคริปต์ -> Windows path เดิม
LARGE_CSV  = _pick_existing(ENV_LARGE,  BASE_DIR / "waterdam_report_large.csv",  WIN_LARGE)
MEDIUM_CSV = _pick_existing(ENV_MEDIUM, BASE_DIR / "waterdam_report_medium.csv", WIN_MEDIUM)

# OUT_CSV ใช้ได้เสมอ (สร้างใหม่ได้) — ถ้าเป็น path Windows บน Linux จะไปสร้างใต้ BASE_DIR
_out_candidate = Path(ENV_OUT)
if _out_candidate.drive:  # ถ้าเป็น path แบบมี drive (C:\...)
    OUT_CSV = BASE_DIR / Path(_out_candidate.name)   # เขียนเป็นชื่อไฟล์เดียวใน BASE_DIR
else:
    OUT_CSV = (BASE_DIR / _out_candidate).resolve()

# ============================== GUARD ==============================
def _fail_missing():
    print("❌ ไม่พบไฟล์อินพุตที่ต้องใช้สำหรับการรวมไฟล์", file=sys.stderr)
    print(f"- คาดหวัง: waterdam_report_large.csv, waterdam_report_medium.csv", file=sys.stderr)
    print(f"- ตำแหน่งค้นหาเริ่มต้น: {BASE_DIR}", file=sys.stderr)
    print("\nวิธีแก้ที่แนะนำ:", file=sys.stderr)
    print("1) วางไฟล์ทั้งสองไว้ในโฟลเดอร์เดียวกับสคริปต์นี้", file=sys.stderr)
    print("2) หรือกำหนด ENV ใน workflow / เครื่องคุณ:", file=sys.stderr)
    print('   LARGE_CSV=path/to/waterdam_report_large.csv', file=sys.stderr)
    print('   MEDIUM_CSV=path/to/waterdam_report_medium.csv', file=sys.stderr)
    sys.exit(1)

if LARGE_CSV is None or MEDIUM_CSV is None:
    _fail_missing()

# ======================== Core (รวมไฟล์ + Clean) ========================
def read_csv_smart(path: Path) -> pd.DataFrame:
    """
    อ่าน CSV แบบทนทาน:
    - ลองหลาย encoding (utf-8-sig, utf-8, cp874, latin-1)
    - เก็บทุกคอลัมน์เป็น string เพื่อลดปัญหา type
    - on_bad_lines='warn' กัน crash ถ้ามีแถวเสียรูป
    """
    encodings = ("utf-8-sig", "utf-8", "cp874", "latin-1")
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(
                path,
                encoding=enc,
                dtype=str,
                low_memory=False,
                on_bad_lines="warn",
            )
        except UnicodeDecodeError as e:
            last_err = e
            continue
    # ถ้ายังไม่ผ่าน ลอง auto อีกครั้ง
    try:
        return pd.read_csv(path, dtype=str, low_memory=False, on_bad_lines="warn")
    except Exception as e:
        raise RuntimeError(f"อ่านไฟล์ไม่ได้: {path} (last_err={last_err}, err={e})")

def run_merge_only():
    print(f"📥 อ่านไฟล์ใหญ่  : {LARGE_CSV}")
    print(f"📥 อ่านไฟล์กลาง : {MEDIUM_CSV}")

    df_large  = read_csv_smart(LARGE_CSV)
    df_medium = read_csv_smart(MEDIUM_CSV)

    # ให้คอลัมน์ตรงกัน (รวมแบบ union แล้วจัด order ตาม df_large)
    ordered_cols = list(df_large.columns)
    for c in ordered_cols:
        if c not in df_medium.columns:
            df_medium[c] = pd.NA
    # เผื่อมีคอลัมน์เกินใน df_medium ให้ตัดทิ้งเพื่อให้ตรง order
    df_medium = df_medium[ordered_cols]

    # ติด tag ประเภทเขื่อน
    df_large["DamType"]  = "large"
    df_medium["DamType"] = "medium"

    # รวม
    df = pd.concat([df_large, df_medium], ignore_index=True)

    # ทำความสะอาดเบื้องต้น (ทำทุกคอลัมน์แบบ string)
    df = df.fillna("0")
    # แทนค่าขีด/ว่างเป็น "0"
    df = df.replace({"-": "0", "--": "0", "–": "0", "—": "0", "": "0"})
    # ตัด space ซ้ายขวา
    df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)

    # ลบแถวซ้ำ
    before = len(df)
    df = df.drop_duplicates()
    deduped = before - len(df)
    if deduped > 0:
        print(f"🧹 ลบแถวซ้ำ {deduped:,} แถว")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"💾 รวมไฟล์แล้ว: {OUT_CSV} ({len(df):,} แถว)")
    return len(df), str(OUT_CSV)

# ================================== MAIN ==================================
def main():
    t0 = time.time()
    rows, out_path = run_merge_only()
    elapsed = time.time() - t0
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(
        f"[WaterDam MERGE] OK rows={rows} @ {when}\n"
        f"รวมไฟล์เสร็จแล้ว\n"
        f"- แถว: {rows}\n"
        f"- ไฟล์: {out_path}\n"
        f"- ใช้เวลา: {elapsed:.2f} วินาที\n"
    )

if __name__ == "__main__":
    main()
