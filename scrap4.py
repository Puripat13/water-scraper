# -*- coding: utf-8 -*-
import os, re, json
import pandas as pd

CSV_LARGE  = os.getenv("CSV_LARGE",  "waterdam_report_large.csv")
CSV_MEDIUM = os.getenv("CSV_MEDIUM", "waterdam_report_medium.csv")
CSV_OUT    = os.getenv("CSV_OUT",    "waterdam_report.csv")

ENABLE_UPLOAD = os.getenv("ENABLE_GOOGLE_DRIVE_UPLOAD", "true").lower() == "true"
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON", "")

TARGET_ORDER = [
    "Dam", "Location", "Capacity_Total", "Capacity_Usable",
    "Water_Stored", "Water_Usable", "Inflow", "Outflow",
    "Data_Time", "Water_Type", "Water_Stored_pct", "Water_Usable_pct"
]
TEXT_COLS = {"Dam","Location","Water_Type","Data_Time"}
PCT_RE  = re.compile(r"\(([-+]?\d*\.?\d+)\s*%?\)")

def read_csv(path):
    for enc in ("utf-8-sig","utf-8"):
        try: return pd.read_csv(path, encoding=enc)
        except: pass
    return pd.read_csv(path)

def unify_columns(df1, df2):
    ordered = list(df1.columns)
    for c in df2.columns:
        if c not in ordered: ordered.append(c)
    def _reorder(df):
        for c in ordered:
            if c not in df.columns: df[c] = pd.NA
        return df[ordered]
    return _reorder(df1), _reorder(df2)

def extract_pct(df):
    for col in list(df.columns):
        s = df[col].astype(str)
        if s.str.contains(PCT_RE).any():
            df[col+"_pct"] = s.str.extract(PCT_RE)[0].astype(float).div(100)
            df[col] = s.str.replace(PCT_RE,"",regex=True).str.strip()
    return df

def force_schema(df):
    for c in TARGET_ORDER:
        if c not in df.columns:
            df[c] = "" if c in TEXT_COLS else pd.NA
    df = df[TARGET_ORDER].copy()
    # numeric -> 0, text -> ""
    num_cols = [c for c in df.columns if c not in TEXT_COLS]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    for c in TEXT_COLS:
        df[c] = df[c].fillna("")
    return df

# ---------- Drive upload ----------
def upload_many(paths):
    if not ENABLE_UPLOAD: 
        print("ℹ️ Skip upload"); return
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    drive = build("drive","v3",credentials=creds,cache_discovery=False)
    drive.files().get(fileId=DRIVE_FOLDER_ID, fields="id", supportsAllDrives=True).execute()
    def upsert(p):
        if not os.path.exists(p): return
        fname = os.path.basename(p)
        q = f"name='{fname}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false"
        res = drive.files().list(q=q, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = res.get("files", [])
        media = MediaFileUpload(p, mimetype="text/csv", resumable=True)
        if files:
            fid = files[0]["id"]
            drive.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
            print(f"✅ Updated {fname}")
        else:
            meta = {"name":fname,"parents":[DRIVE_FOLDER_ID]}
            drive.files().create(body=meta, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"✅ Created {fname}")
    for f in paths: upsert(f)

def main():
    if not os.path.exists(CSV_LARGE) or not os.path.exists(CSV_MEDIUM):
        raise FileNotFoundError("❌ Run scrap3.py first to generate input files")
    dfL = read_csv(CSV_LARGE)
    dfM = read_csv(CSV_MEDIUM)
    dfL, dfM = unify_columns(dfL, dfM)
    df = pd.concat([dfL, dfM], ignore_index=True)
    df = extract_pct(df)
    df = force_schema(df)
    df.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"💾 Saved {CSV_OUT} rows={len(df)}")
    upload_many([CSV_LARGE, CSV_MEDIUM, CSV_OUT])

if __name__=="__main__":
    main()
