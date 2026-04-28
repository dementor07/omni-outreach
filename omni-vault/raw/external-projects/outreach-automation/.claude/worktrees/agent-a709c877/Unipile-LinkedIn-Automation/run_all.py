import subprocess
import os
import sys
import time

# ==========================================================
# Helper: Run any script safely
# ==========================================================
def run_script(script_name):
    print("\n" + "="*70)
    print(f"🚀 Running: {script_name}")
    print("="*70)

    # Check file exists
    if not os.path.exists(script_name):
        print(f"❌ ERROR: {script_name} not found!")
        sys.exit(1)

    # Run script
    result = subprocess.run([sys.executable, script_name])

    # Check return code
    if result.returncode != 0:
        print(f"❌ ERROR: {script_name} failed!")
        sys.exit(result.returncode)

    print(f"✅ Completed: {script_name}")
    print("⏳ Waiting 3 seconds before next script...\n")
    time.sleep(3)  # ⭐ Recommended delay


# ==========================================================
# Main Pipeline Execution
# ==========================================================
def main():
    print("\n" + "="*70)
    print("🔥 Starting Full Unipile LinkedIn Automation Pipeline")
    print("="*70)

    # Step 1
    run_script("1_convert_to_members_csv.py")

    # Step 2
    run_script("2_prepare_slugs.py")

    # Step 3
    run_script("3_linkledin_filter.py")

    # Step 4
    run_script("4_fetch_provider_ids.py")

    # Step 5
    run_script("5_send_invitations.py")

    # Step 6
    run_script("6_send_message.py")

    # Step 7
    run_script("7_send_followups.py")

    print("\n" + "="*70)
    print("🎉 Pipeline Completed Successfully!")
    print("="*70)


# ==========================================================
# Entry point
# ==========================================================
if __name__ == "__main__":
    main()
