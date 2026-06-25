import re
import os

env_path = "/home/omni-v2/.env"

if os.path.exists(env_path):
    with open(env_path, "r") as f:
        content = f.read()
    
    # Check if ALEMBIC_DATABASE_URL exists, if not add it
    if "ALEMBIC_DATABASE_URL" not in content:
        # Extract existing DATABASE_URL to use as ALEMBIC_DATABASE_URL
        match = re.search(r"DATABASE_URL=(.*)", content)
        if match:
            existing_url = match.group(1)
            content += f"\nALEMBIC_DATABASE_URL={existing_url}\n"
    
    # Update DATABASE_URL
    new_url = "postgresql://omni_app_role:omni_app_password@db:5432/outreach"
    content = re.sub(r"DATABASE_URL=.*", f"DATABASE_URL={new_url}", content)
    
    with open(env_path, "w") as f:
        f.write(content)
    print(".env updated successfully")
else:
    print(f"{env_path} not found")
