# -*- coding: utf-8 -*-
import os, re, time, tempfile, json
import pandas as pd

# ======== I/O ========
LARGE_CSV  = os.getenv("CSV_LARGE",  "waterdam_report_large.csv")
MEDIUM_CSV = os.getenv("CSV_MEDIUM", "waterdam_report_medium.csv")
OUT_CSV    = os.getenv("CSV_OUT",    "waterdam_report.csv")

# ======== Clean Params ========
MISSING_RATIO_THRESHOLD = float(os.getenv("MISSING_RATIO_THRESHOLD", "0.8"))
MIN_VALID_COUNT = int(os.getenv("MIN_VALID_COUNT", "2"))

# ======== Google Drive Upload ========
ENABLE_GOOGLE_DRIVE_UPLOAD = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "true").lower() == "true"
# อ่าน folder id จาก ENV ได้ 2 ชื่อ (เผื่อไว้ให้เข้ากับ repo เดิม)
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID") or os.getenv("PURIPAT_ID", "")
CSV_MIMETYPE = "text/csv"

# ======== Service Account Handling (จาก secrets) ========
def _resolve_sa_file():
    """
    - ถ้ามี ENV SERVICE_ACCOUNT_JSON (เป็นเนื้อหา JSON) -> สร้างไฟล์ชั่วคราวแล้วคืน path
    - else ถ้ามี SERVICE_ACCOUNT_FILE และไฟล์มีอยู่จริง -> ใช้ไฟล์นั้น
    - else -> raise error
    """
    sa_json_str = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
    sa_file_env = os.getenv("SERVICE_ACCOUNT_FILE", "githubproject-467507-653192ee67bf.json")

    if sa_json_str:
        try:
            # validate เป็น JSON ก่อน
            _ = json.loads(sa_json_str)
            tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
            tmp.write(sa_json_str)
            tmp.flush()
            tmp.close()
            return tmp.name
        except Exception as e:
            raise RuntimeError(f"Invalid SERVICE_ACCOUNT_JSON: {e}")

    if os.path.exists(sa_file_env):
        return sa_file_env

    raise FileNotFoundError(
        "ไม่พบ Service Account (SERVICE_ACCOUNT_JSON หรือ SERVICE_ACCOUNT_FILE)"
    )

# ======== Drive Helpers ========
def _build_drive_service_with_service_account(sa_path):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def drive_find_file_in_folder(service, filename, folder_id):
    fname = filename.replace("'", "\\'")
    q = f"name = '{fname}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    return res.get("files", [])

def drive_upload_or_update_csv(local_path, drive_folder_id, target_name=None, max_retries=3):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    if target_name is None:
        target_name = os.path.basename(local_path)

    sa_path = _resolve_sa_file()
    service = _build_drive_service_with_service_account(sa_path)
    media = MediaFileUpload(local_path, mimetype=CSV_MIMETYPE, resumable=True)
    exists = drive_find_file_in_folder(service, target_name, drive_folder_id)

    for attempt in range(1, max_retries + 1):
        try:
            if exists:
                file_id = exists[0]["id"]
                updated = service.files().update(fileId=file_id, media_body=media).execute()
                return ("update", updated.get("id"))
            else:
                file_metadata = {"name": target_name, "parents": [drive_folder_id]}
                created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
                return ("create", created.get("id"))
        except HttpError as e:
            if attempt >= max_retries:
                raise
            time.sleep(2 * attempt)

# ======== ETL Core ========
def read_csv_smart(path):
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)

def unify_columns_with_order(df, ordered_cols):
    for c in ordered_cols:
        if c not in df.columns:
            df[c] = pd.NA
    extras = [c for c in df.columns if c not in ordered_cols]
    return df[ordered_cols + extras]

def is_bad_value(x):
    if pd.isna(x):
        return True
    s = str(x).strip()
    return (s in ["", "-", "--", "—", "–"])

def clean_and_filter(df):
    df = df.replace({ "-": pd.NA, "--": pd.NA, "—": pd.NA, "–": pd.NA, "": pd.NA })
    patt_id = re.compile(r"(name|station|dam|เขื่อน|province|จังหวัด|date|วันที่|time|เวลา)", re.I)
    id_like = [c for c in df.columns if patt_id.search(str(c))]
    data_cols = [c for c in df.columns if c not in id_like]
    if not data_cols:
        data_cols = df.columns.tolist()

    is_bad = df[data_cols].applymap(is_bad_value)
    missing_ratio = is_bad.mean(axis=1)
    valid_count = (~is_bad).sum(axis=1)
    mask_drop = (missing_ratio >= MISSING_RATIO_THRESHOLD) | (valid_count < MIN_VALID_COUNT)
    return df[~mask_drop].copy(), id_like, data_cols

# ✅ regex รองรับค่าลบ เช่น (-12.3%)
_pct_re = re.compile(r"\(([-+]?\d*\.?\d+)\s*%?\)")

def make_and_strip_parentheses_pct(df):
    for col in df.columns:
        col_str = df[col].astype(str)
        if col_str.str.contains(_pct_re).any():
            nums = col_str.str.extract(_pct_re)[0].astype(float).div(100)
            df[col + "_pct"] = nums
            df[col] = (
                col_str
                .str.replace(_pct_re, "", regex=True)
                .str.replace(r"\(--\s*%?\)", "", regex=True)
                .str.strip()
            )
    return df

_num_strip_replacements = [
    (r",", ""),           
    (r"%", ""),           
    (r"\s+", ""),         
    (r"^—$|^–$|^-$", ""), 
]

def coerce_numeric_columns(df, id_like_cols):
    candidate_cols = [c for c in df.columns if c not in id_like_cols and not str(c).lower().endswith("_pct")]
    for col in candidate_cols:
        s = df[col].astype(str)
        if s.str.contains(r"[A-Za-zก-๙]", regex=True).mean() > 0.7:
            continue
        for pat, rep in _num_strip_replacements:
            s = s.str.replace(pat, rep, regex=True)
        s = s.str.replace("–", "-", regex=False).str.replace("—", "-", regex=False)
        s = s.replace("", pd.NA)
        df[col] = pd.to_numeric(s, errors="coerce")
    df[candidate_cols] = df[candidate_cols].fillna(0)
    return df

def detect_and_sort_by_date(df):
    candidates_order = ["Date", "วันที่", "Data_Date", "DataDate", "Data_Time", "DataTime", "Time", "เวลา"]
    regex_candidates = re.compile(r"(date|วันที่|data_?time|เวลา)", re.I)
    col_candidate = None
    for c in candidates_order:
        if c in df.columns:
            col_candidate = c; break
    if col_candidate is None:
        for c in df.columns:
            if regex_candidates.search(str(c)):
                col_candidate = c; break
    if col_candidate is None:
        return df
    sort_key = pd.to_datetime(df[col_candidate], dayfirst=True, errors="coerce")
    if sort_key.notna().mean() < 0.3:
        sort_key = pd.to_datetime(df[col_candidate], dayfirst=False, errors="coerce")
    return df.assign(_sort_key=sort_key).sort_values("_sort_key", kind="stable").drop(columns=["_sort_key"])

def assert_inputs_exist():
    missing = [p for p in (LARGE_CSV, MEDIUM_CSV) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(f"❌ ไม่พบไฟล์อินพุต: {missing}. กรุณาตรวจสอบว่าขั้นตอนก่อนหน้าสร้างไฟล์ครบแล้ว")

def main():
    assert_inputs_exist()

    df_large  = read_csv_smart(LARGE_CSV)
    df_medium = read_csv_smart(MEDIUM_CSV)

    ordered_cols = list(df_large.columns)
    for c in df_medium.columns:
        if c not in ordered_cols:
            ordered_cols.append(c)
    df_large  = unify_columns_with_order(df_large, ordered_cols)
    df_medium = unify_columns_with_order(df_medium, ordered_cols)

    df = pd.concat([df_large, df_medium], ignore_index=True)
    df, id_like_cols, _ = clean_and_filter(df)
    df = make_and_strip_parentheses_pct(df)
    df = coerce_numeric_columns(df, id_like_cols)
    df = detect_and_sort_by_date(df)

    # ✅ เติม 0 ทุกคอลัมน์ที่ยังว่างอยู่
    df = df.fillna(0)

    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"💾 Saved {OUT_CSV} rows={len(df)} cols={len(df.columns)}")

    if ENABLE_GOOGLE_DRIVE_UPLOAD:
        if not DRIVE_FOLDER_ID:
            raise RuntimeError("ENABLE_GOOGLE_DRIVE_UPLOAD=true แต่ไม่ได้ตั้งค่า DRIVE_FOLDER_ID / PURIPAT_ID")
        action, file_id = drive_upload_or_update_csv(
            local_path=OUT_CSV,
            drive_folder_id=DRIVE_FOLDER_ID,
            target_name=os.path.basename(OUT_CSV)
        )
        verb = "อัปเดตไฟล์" if action == "update" else "อัปโหลดไฟล์ใหม่"
        print(f"✅ {verb}ไปยัง Google Drive (fileId={file_id})")
    else:
        print("ℹ️ ข้ามการอัปโหลด Google Drive (ENABLE_GOOGLE_DRIVE_UPLOAD=false)")

if __name__ == "__main__":
    main()
