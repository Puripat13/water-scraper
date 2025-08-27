# -*- coding: utf-8 -*-
import os, re, time, json, io, tempfile, sys
import pandas as pd

CSV_LARGE  = os.getenv("CSV_LARGE",  "waterdam_report_large.csv")
CSV_MEDIUM = os.getenv("CSV_MEDIUM", "waterdam_report_medium.csv")
CSV_OUT    = os.getenv("CSV_OUT",    "waterdam_report.csv")

# cleaning params
MISSING_RATIO_THRESHOLD = float(os.getenv("MISSING_RATIO_THRESHOLD", "0.8"))
MIN_VALID_COUNT = int(os.getenv("MIN_VALID_COUNT", "2"))

# upload params
ENABLE_GOOGLE_DRIVE_UPLOAD = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "true").lower() == "true"
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON", "")

# ---- Target columns (บังคับคอลัมน์และลำดับ) ----
TARGET_ORDER = [
    "Dam", "Location", "Capacity_Total", "Capacity_Usable",
    "Water_Stored", "Water_Usable", "Inflow", "Outflow",
    "Data_Time", "Water_Type", "Water_Stored_pct", "Water_Usable_pct"
]

# ---------- Helpers ----------
def read_csv_smart(path_or_buf):
    try:
        return pd.read_csv(path_or_buf, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path_or_buf, encoding="utf-8")
    except Exception:
        return pd.read_csv(path_or_buf)

def unify_columns_with_order(df, ordered_cols):
    for c in ordered_cols:
        if c not in df.columns: df[c] = pd.NA
    extras = [c for c in df.columns if c not in ordered_cols]
    return df[ordered_cols + extras]

def is_bad_value(x):
    if pd.isna(x): return True
    s = str(x).strip()
    return s in ["", "-", "--", "—", "–"]

def clean_and_filter(df):
    df = df.replace({ "-": pd.NA, "--": pd.NA, "—": pd.NA, "–": pd.NA, "": pd.NA })
    patt_id = re.compile(r"(name|station|dam|เขื่อน|province|จังหวัด|date|วันที่|time|เวลา)", re.I)
    id_like = [c for c in df.columns if patt_id.search(str(c))]
    data_cols = [c for c in df.columns if c not in id_like] or df.columns.tolist()
    is_bad = df[data_cols].applymap(is_bad_value)
    missing_ratio = is_bad.mean(axis=1)
    valid_count = (~is_bad).sum(axis=1)
    mask_drop = (missing_ratio >= MISSING_RATIO_THRESHOLD) | (valid_count < MIN_VALID_COUNT)
    return df[~mask_drop].copy(), id_like

_pct_re = re.compile(r"\(([-+]?\d*\.?\d+)\s*%?\)")

def make_and_strip_parentheses_pct(df):
    # สร้าง *_pct จากค่าในวงเล็บ (A%) และลบวงเล็บออกจากคอลัมน์เดิม
    for col in list(df.columns):
        s = df[col].astype(str)
        if s.str.contains(_pct_re).any():
            nums = s.str.extract(_pct_re)[0].astype(float).div(100)
            df[col + "_pct"] = nums
            df[col] = (
                s.str.replace(_pct_re, "", regex=True)
                 .str.replace(r"\(--\s*%?\)", "", regex=True)
                 .str.strip()
            )
    return df

_num_strip = [(r",",""), (r"%",""), (r"\s+",""), (r"^—$|^–$|^-$","")]

def coerce_numeric_columns(df, id_like_cols):
    candidates = [c for c in df.columns if c not in id_like_cols and not str(c).lower().endswith("_pct")]
    for col in candidates:
        s = df[col].astype(str)
        # ถ้าเป็น text ส่วนใหญ่ ข้าม
        if s.str.contains(r"[A-Za-zก-๙]", regex=True).mean() > 0.7:
            continue
        for pat, rep in _num_strip:
            s = s.str.replace(pat, rep, regex=True)
        s = s.str.replace("–", "-", regex=False).str.replace("—", "-", regex=False)
        s = s.replace("", pd.NA)
        df[col] = pd.to_numeric(s, errors="coerce")
    df[candidates] = df[candidates].fillna(0)
    return df

def detect_and_sort_by_date(df):
    order = ["Date","วันที่","Data_Date","DataDate","Data_Time","DataTime","Time","เวลา","DataTimeStr"]
    regex_candidates = re.compile(r"(date|วันที่|data_?time|เวลา)", re.I)
    key = None
    for c in order:
        if c in df.columns: key = c; break
    if key is None:
        for c in df.columns:
            if regex_candidates.search(str(c)): key = c; break
    if key is None: return df
    s = pd.to_datetime(df[key], dayfirst=True, errors="coerce")
    if s.notna().mean() < 0.3:
        s = pd.to_datetime(df[key], dayfirst=False, errors="coerce")
    return df.assign(_sort=s).sort_values("_sort", kind="stable").drop(columns=["_sort"])

def force_to_target_order(df):
    # เติมคอลัมน์ที่ขาด
    for c in TARGET_ORDER:
        if c not in df.columns:
            # เลือก default เหมาะกับชนิดข้อมูล
            df[c] = 0 if c.endswith("_pct") or c not in ("Dam","Location","Data_Time","Water_Type") else 0
    # จัดเรียง
    return df[TARGET_ORDER].copy()

def assert_inputs():
    missing = [p for p in (CSV_LARGE, CSV_MEDIUM) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(f"❌ Missing inputs: {missing}. Please run scrap3.py first.")

# ---------- Drive ----------
def upload_to_drive(local_csv):
    if not ENABLE_GOOGLE_DRIVE_UPLOAD:
        print("ℹ️ Skip Drive upload (ENABLE_GOOGLE_DRIVE_UPLOAD=false)")
        return
    if not DRIVE_FOLDER_ID or not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Drive upload enabled but DRIVE_FOLDER_ID or SERVICE_ACCOUNT_JSON is missing")

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    # verify folder
    drive.files().get(fileId=DRIVE_FOLDER_ID, fields="id,name,driveId",
                      supportsAllDrives=True).execute()

    fname = os.path.basename(local_csv).replace("'", "\\'")
    q = f"name = '{fname}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    res = drive.files().list(q=q, fields="files(id,name)",
                             supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = res.get("files", [])
    media = MediaFileUpload(local_csv, mimetype="text/csv", resumable=True)

    if files:
        fid = files[0]["id"]
        drive.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
        print(f"✅ Updated on Drive: {fname} (fileId={fid})")
    else:
        meta = {"name": fname, "parents": [DRIVE_FOLDER_ID]}
        created = drive.files().create(body=meta, media_body=media, fields="id",
                                       supportsAllDrives=True).execute()
        fid = created["id"]
        print(f"✅ Created on Drive: {fname} (fileId={fid})")

# ---------- Main ----------
def main():
    assert_inputs()

    dfL = read_csv_smart(CSV_LARGE)
    dfM = read_csv_smart(CSV_MEDIUM)

    # รวมให้ครบคอลัมน์ก่อน
    ordered = list(dfL.columns)
    for c in dfM.columns:
        if c not in ordered:
            ordered.append(c)
    dfL = unify_columns_with_order(dfL, ordered)
    dfM = unify_columns_with_order(dfM, ordered)

    df = pd.concat([dfL, dfM], ignore_index=True)

    # clean
    df, id_like_cols = clean_and_filter(df)
    df = make_and_strip_parentheses_pct(df)
    df = coerce_numeric_columns(df, id_like_cols)
    df = detect_and_sort_by_date(df)

    # บังคับคอลัมน์ตามมาตรฐาน
    df = force_to_target_order(df)
    # เติมค่าว่างเป็น 0
    df = df.fillna(0)

    df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"💾 Saved {CSV_OUT} rows={len(df)} cols={len(df.columns)}")

    upload_to_drive(CSV_OUT)

if __name__ == "__main__":
    main()
