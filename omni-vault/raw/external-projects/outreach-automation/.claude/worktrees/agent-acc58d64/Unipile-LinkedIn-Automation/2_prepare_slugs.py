import pandas as pd
import re

# Input and output CSV
input_csv = "members.csv"
output_csv = "member_slugs_ready.csv"

# Read CSV
df = pd.read_csv(input_csv)

if 'LinkedIn_URL' not in df.columns:
    raise ValueError("CSV must have a column named 'LinkedIn_URL'")

# Function to extract LinkedIn username slug
def extract_slug(link):
    if pd.isna(link):
        return None
    link = str(link).strip()
    # Extract username from full URL
    match = re.search(r'linkedin\.com/in/([\w\-\d]+)', link)
    if match:
        return match.group(1)  # only username, no 'in/' prefix
    # If it already looks like a slug, return as is
    return link if re.match(r'^[\w\-\d]+$', link) else None

df['slug'] = df['LinkedIn_URL'].apply(extract_slug)

# Drop rows where slug could not be extracted
df_clean = df.dropna(subset=['slug'])

# Save clean CSV
df_clean.to_csv(output_csv, index=False)
print(f"Processed CSV saved to '{output_csv}'")
print(df_clean[['LinkedIn_URL', 'slug']].head())
