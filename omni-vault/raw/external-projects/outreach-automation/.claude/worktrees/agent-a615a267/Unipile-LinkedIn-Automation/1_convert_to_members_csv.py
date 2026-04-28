# convert_to_members_csv_robust.py
# Robust extractor: finds LinkedIn URLs anywhere in the sheet and maps a sensible Name.
# Produces members.csv with columns: LinkedIn_URL,Name
#
# Usage:
#   python convert_to_members_csv_robust.py  # expects 20251107.xlsx in same folder
#
import pandas as pd
import re
import os
from urllib.parse import urlparse

INPUT_XLSX = "ProductHunt_export.xlsx"
OUTPUT_CSV = "members.csv"

# regex to find linkedin URL-like substrings (with or without scheme)
LINKEDIN_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?)?linkedin\.com(?:/[^ ,;\n\r\t]*)?",
    flags=re.IGNORECASE,
)

def find_linkedin_in_text(text):
    if not isinstance(text, str):
        return None
    text = text.strip()
    m = LINKEDIN_RE.search(text)
    if not m:
        return None
    url = m.group(0)
    # normalize: ensure scheme
    if not url.lower().startswith("http"):
        url = "https://" + url
    return url.rstrip('.,;')

def normalize_name(name):
    if pd.isna(name):
        return ""
    s = str(name).strip()
    # ignore placeholders that are zeros or "nan"
    if s == "0" or s.lower() == "nan" or s == "":
        return ""
    return s

def candidate_name_from_row(row, prefer_cols=None):
    # prefer_cols: list of col names in order to try
    if prefer_cols:
        for c in prefer_cols:
            if c in row.index:
                n = normalize_name(row[c])
                if n:
                    return n
    # fallback: find any column with "name" in header
    for c in row.index:
        if "name" in str(c).lower():
            n = normalize_name(row[c])
            if n:
                return n
    # fallback: try MakerX_Name patterns
    for c in row.index:
        if re.search(r"maker\d+.*name", str(c), re.IGNORECASE):
            n = normalize_name(row[c])
            if n:
                return n
    return ""

def extract_all_links_and_names(df):
    records = []
    seen_links = set()
    # Precompute columns that look like maker/link or maker/linkedin or name
    maker_link_cols = [c for c in df.columns if re.search(r"maker\d+.*link", str(c), re.IGNORECASE)]
    linkedin_like_cols = [c for c in df.columns if "linkedin" in str(c).lower()]
    name_cols = [c for c in df.columns if "name" in str(c).lower()]

    # First pass: scan row-wise and look into each cell for linkedin substring,
    # while trying to map to preferred name columns (MakerX_Name if MakerX_Linkedin exists)
    for idx, row in df.iterrows():
        # search each cell for linkedin url
        for col in df.columns:
            cell = row[col]
            link = find_linkedin_in_text(cell)
            if link:
                # try to map name:
                name = ""
                # If column is MakerX_Linkedin or MakerX_Link, try to derive maker number and prefer MakerX_Name
                m = re.search(r"maker(\d+)", str(col), re.IGNORECASE)
                if m:
                    maker_num = m.group(1)
                    # prefer Maker{num}_Name or Maker{num}_Name variants
                    prefer_cols = []
                    for candidate in df.columns:
                        if re.search(fr"maker{maker_num}.*name", str(candidate), re.IGNORECASE):
                            prefer_cols.append(candidate)
                    # also include common variations
                    prefer_cols += [c for c in df.columns if re.search(fr"maker{maker_num}", str(c), re.IGNORECASE) and "name" in str(c).lower()]
                    name = candidate_name_from_row(row, prefer_cols)
                # fallback to other name columns
                if not name:
                    name = candidate_name_from_row(row, name_cols)
                # final fallback: parse from URL path (last path segment)
                if not name:
                    try:
                        path = urlparse(link).path.strip("/")
                        # prefer last segment after /in/ or last segment
                        segs = [s for s in path.split("/") if s]
                        if segs:
                            candidate = segs[-1].replace("-", " ").replace("_", " ").title()
                            if candidate and not candidate.lower().startswith("company"):
                                name = candidate
                    except Exception:
                        name = ""
                # Normalize link (remove tracking params)
                link_parsed = urlparse(link)
                clean_path = link_parsed.path
                clean_netloc = link_parsed.netloc
                clean_url = f"https://{clean_netloc}{clean_path}"
                clean_url = clean_url.rstrip("/")
                if clean_url not in seen_links:
                    seen_links.add(clean_url)
                    records.append((clean_url, name if name else "Unknown"))
    return records

def main():
    if not os.path.exists(INPUT_XLSX):
        print(f"Error: input file not found: {INPUT_XLSX}")
        return

    df = pd.read_excel(INPUT_XLSX)
    # strip column headers of leading/trailing whitespace (do not change names otherwise)
    df.rename(columns=lambda c: c.strip() if isinstance(c, str) else c, inplace=True)

    records = extract_all_links_and_names(df)
    members_df = pd.DataFrame(records, columns=["LinkedIn_URL", "Name"])
    # final cleaning: drop duplicates, ensure linkedin domain present
    members_df["LinkedIn_URL"] = members_df["LinkedIn_URL"].astype(str)
    members_df = members_df[members_df["LinkedIn_URL"].str.contains("linkedin.com", case=False, na=False)]
    members_df = members_df.drop_duplicates(subset=["LinkedIn_URL"]).reset_index(drop=True)

    members_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"✅ Members file created: {os.path.abspath(OUTPUT_CSV)}")
    print(f"Total members extracted: {len(members_df)}")

    # print brief column-wise summary (helpful for debugging/skew)
    counts = {}
    for c in df.columns:
        try:
            cnt = df[c].astype(str).str.contains(r"linkedin\.com", case=False, na=False).sum()
            if cnt > 0:
                counts[c] = int(cnt)
        except Exception:
            continue
    if counts:
        print("\nLinkedIn counts by column:")
        for k, v in counts.items():
            print(f"  {k}: {v}")
    else:
        print("\nNo linkedin links detected by column search (script still may have found URLs inside free-text cells).")

if __name__ == "__main__":
    main()
