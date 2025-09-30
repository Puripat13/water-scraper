# -*- coding: utf-8 -*-
import os, time
import pandas as pd
from pathlib import Path
from datetime import datetime

# ============== I/O (ไฟล์เข้า/ออก) ============== #
LARGE_CSV  = Path(r"C:\Project_End\CodeProject\waterdam_report_large.csv").resolve()
MEDIUM_CSV = Path(r"C:\Project_End\CodeProject\waterdam_report_medium.csv").resolve()
OUT_CSV    = Path(r"C:\Project_End\CodeProject\waterdam_report.csv").resolve()

# ======================== Core (รวมไฟล์ + Clean) ======================== #
def read_csv_smart(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)

def run_merge_only():
    df_large  = read_csv_smart(LARGE_CSV)
    df_medium = read_csv_smart(MEDIUM_CSV)

    # ให้คอลัมน์ตรงกัน
    ordered_cols = list(df_large.columns)
    for c in ordered_cols:
        if c not in df_medium.columns:
            df_medium[c] = pd.NA
    df_medium = df_medium[ordered_cols]

    df_large["DamType"]  = "large"
    df_medium["DamType"] = "medium"

    df = pd.concat([df_large, df_medium], ignore_index=True)

    # ✅ แทนค่า missing ให้เป็น "0"
    df = df.fillna("0")
    df = df.replace({"-": "0", "--": "0", "–": "0", "—": "0", "": "0"})

    # ลบแถวซ้ำ
    df = df.drop_duplicates()

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"💾 รวมไฟล์แล้ว: {OUT_CSV} ({len(df):,} แถว)")

    return len(df), str(OUT_CSV)

# ================================== MAIN ================================== #
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
