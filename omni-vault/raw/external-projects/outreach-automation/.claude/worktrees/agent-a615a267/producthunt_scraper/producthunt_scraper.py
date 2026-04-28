import subprocess
import sys
import datetime
import os

# 🔧 FORCE UTF-8 FOR THIS PROCESS (CRITICAL)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==========================
# CONFIG
# ==========================
SCRIPTS = [
    "archive_scraper.py",
    "product_scraper.py",
    "profile_scraper.py",
    "converter_to_leads.py"
]

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = os.path.join(LOG_DIR, f"run_{timestamp}.log")

# ==========================
# HELPERS
# ==========================
def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{timestamp}] {msg}"
    print(message)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def run_script(script_name):
    log(f"▶ Running {script_name}")

    result = subprocess.run(
        [sys.executable, script_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",     # 🔧 FORCE UTF-8 DECODING
        errors="replace"      # 🔧 NEVER CRASH ON BAD BYTES
    )

    if result.stdout:
        log(result.stdout)

    if result.returncode != 0:
        log(f"[ERROR] {script_name} failed")
        log(result.stderr)
        raise RuntimeError(f"{script_name} failed")

    log(f"[OK] Completed {script_name}")


def main():
    log("Product Hunt automation started")

    for script in SCRIPTS:
        run_script(script)

    log("Product Hunt automation finished successfully")


if __name__ == "__main__":
    main()
