import pandas as pd
import re
import glob
import os
import gspread
from google.oauth2.service_account import Credentials

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ==========================
# GOOGLE SHEET CONFIG
# ==========================
SPREADSHEET_ID = "1lKVSAMMFM0r42X1r3whxkCneC2113jb4LaFfnLW7Ny4"
SHEET_NAME = "producthunt_leads"

# ==========================
# EMBEDDED SERVICE ACCOUNT
# ==========================
SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "linkedin-outreach-483409",
    "private_key_id": "b080c506fbae9349cb646aac549c736bbcfeb62f",
    "private_key": """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCuch2F1yXdENKZ
0WiDaET2P/JLh5XCe64uNzmUzZ3FtUoQgiBSdZ1GbpszfcYkhm1St6lcmDRy7Awu
JzwnSwfbRgn7HIrqrYsOOxjlUWFZsLIXBktpICv5fVPT3F7KWltRO4QO6OxmFIut
DqJJZL7+YhhxAcMDGUDjvlM4q/QCRj384Eu2gflSprZYDac35zCEvUjxHzpWXZ4A
Be2qCyU1EwEUGxTFoEcBe+Qp4UnLFKMKgUN/8Tyb+94Zj/dy1fY6j18IZjlPo2jT
9HB/5VdNMam9GF74r+t+Vvm3fGSprc1+1dUNzb9UKueRXx7yDRtYz1186PJ6WYVi
wCr6GgeRAgMBAAECggEAGvU8HjuQGKBZp1ce61XA+HwL1cO7bz1dPruejKIU3GGG
c1QkqhGObzy3A8dPSEQ030hOJibITi0vua8rAth7u5VQhAuWZStR9q5Hy+JeZLWj
Y97/ZtzHpuvI+U/QHz3E6GIF56bzp1fL+P+usSBeSqH+rHINAKzVpAw8wKCEGhie
+P3u8piJh222kSLqvIl1tXqTdNfhMSTLgkwgSSywm/dS50wZnroIzitp5F74Lh+s
dzpQ5JT1HdOgqunKRWZu+C8VLaDz4UPjuYUZcOhDOoL6qNw8qBk5ZVo1tVISSxt6
yPufeDQcW3yU3r1+q3zWlRiABIPmINXjc1A/aJ4LhQKBgQDVEouBEfAhA9Uum316
CI3KFYgAgW6/ufzsGpwZ4/SsL4GYOannEDYwDVpnA/kQJbiR7u4Ta+JlsPjaUnn9
m1aKK3aZTV7DoWQnThKqD/h8VYkARPRgPgg5H26v0SJUKEMD9pjGhllHyFIEn9vR
8OxN0RhTf4T/k5iNlpSgSfKd7QKBgQDRl1rxFqu8+LmUjkzarObgRx/GFzlFdXhl
BrTKaEdgcTF2CEAa7QOG7qpZnskgctp4DRcjMIrurxYWIlZSB1rPwVFfCxwmFXwK
kQo2kPHQAlokBeJtBGdq0m8B937IasZMoFyKYokl/l3Y+4AxqU8b09wxh3MciHuD
DnkjBH37tQKBgHJDPK6duQFrdcJFvjdYKPlrLIDg6ExG6ByRdI7p0QcZfszsd3Gj
HvwL3SQLXGBNajpQQDoIC+Pu0LT7r9HRoMn93t79P8l3Xic51gZ/BAlhMVQEpmyK
N4yyj4AXjepFoRKaBnnICE7XXSx/sblXEtH0RLBaXS9VrmSXkOKYZVRNAoGAN50/
5mUroPMm20J/Ji9m+/AjgD69Va78CWKkKmlNN0wR4c4CpKJroyxFS46Us+WGDwD6
OL4yv276H1lxKkcFU8dqPhwGlhxxU6R031HKuHVHUfO1x1O51WCNUCpKHAgpIkAT
Di1jUw+R+3eQ5pyUfz/SV9onM1UL4RTAFAinHVkCgYEAhaCDjrq3V1TukqfXQMG/
xwefFmOD+AKn+637xBTed9XpubKV8x/rFwWX8+9Tp4unpcIWvbz59tr9b3WKZll+
l9QeS/bs0MtXZEvtNskHSxx1tk+6eFx92damHZEMqJm933PAxwex3dnzcPdfz4FB
kNOIBErrwDo3EU7sFllR9+A=
-----END PRIVATE KEY-----""",
    "client_email": "linkedin-outreach@linkedin-outreach-483409.iam.gserviceaccount.com",
    "client_id": "110698249464137941651",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/linkedin-outreach%40linkedin-outreach-483409.iam.gserviceaccount.com"
}

# ==========================
# CLEAN CREDENTIALS (FIX)
# ==========================
def get_clean_service_account_info():
    return {
        "type": "service_account",
        "project_id": SERVICE_ACCOUNT_INFO["project_id"],
        "private_key_id": SERVICE_ACCOUNT_INFO["private_key_id"],
        "private_key": SERVICE_ACCOUNT_INFO["private_key"],
        "client_email": SERVICE_ACCOUNT_INFO["client_email"],
        "client_id": SERVICE_ACCOUNT_INFO["client_id"],
        "auth_uri": SERVICE_ACCOUNT_INFO["auth_uri"],
        "token_uri": SERVICE_ACCOUNT_INFO["token_uri"],
        "auth_provider_x509_cert_url": SERVICE_ACCOUNT_INFO["auth_provider_x509_cert_url"],
        "client_x509_cert_url": SERVICE_ACCOUNT_INFO["client_x509_cert_url"],
    }

# ==========================
# LOGIC
# ==========================
MAX_MAKERS = 5


def extract_slug(link):
    if pd.isna(link):
        return None
    match = re.search(r"linkedin\.com/in/([\w\-]+)", str(link))
    return match.group(1) if match else None


def get_latest_csv():
    files = glob.glob("output_final_*.csv")
    if not files:
        raise FileNotFoundError("No output_final CSV found")
    return max(files, key=os.path.getctime)


def push_to_sheet(df):
    creds = Credentials.from_service_account_info(
        get_clean_service_account_info(),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ],
    )

    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

    sheet.clear()
    sheet.update([df.columns.tolist()] + df.values.tolist())


def main():
    input_csv = get_latest_csv()
    df = pd.read_csv(input_csv)

    rows = []

    for _, row in df.iterrows():
        for i in range(1, MAX_MAKERS + 1):
            linkedin = row.get(f"Maker{i}_Linkedin")
            if pd.isna(linkedin):
                continue

            slug = extract_slug(linkedin)
            if not slug:
                continue

            rows.append({
                "LinkedIn_URL": linkedin,
                "Name": row.get(f"Maker{i}_Name", ""),
                "slug": slug,
                "product_name": row.get("Title", "")
            })

    out_df = pd.DataFrame(rows).drop_duplicates(
        subset=["LinkedIn_URL", "product_name"]
    )

    push_to_sheet(out_df)
    print(f"{len(out_df)} leads pushed to Google Sheets")


if __name__ == "__main__":
    main()
