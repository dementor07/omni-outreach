import pandas as pd
import re
import glob
import os

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==========================
# LOGIC
# ==========================
MAX_MAKERS = 5
OUTPUT_FILE = "producthunt_leads.csv"


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


def get_linkedin_value(row, maker_index):
    """
    Safely fetch MakerX_Linkedin regardless of casing
    """
    for col in row.index:
        if col.lower() == f"maker{maker_index}_linkedin".lower():
            return row[col]
    return None


def main():
    input_csv = get_latest_csv()
    df = pd.read_csv(input_csv)

    rows = []

    for _, row in df.iterrows():
        for i in range(1, MAX_MAKERS + 1):

            linkedin = get_linkedin_value(row, i)
            if pd.isna(linkedin) or not linkedin:
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

    out_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    print(f"{len(out_df)} leads saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
