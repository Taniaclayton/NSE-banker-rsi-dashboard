import os
import sys
import time
import shutil
import argparse
import zipfile
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

EOD_FOLDER = os.getenv("EOD_FOLDER")
DOWNLOAD_DIR    = os.getenv("DOWNLOAD_DIR")

URL = "https://www.samco.in/bhavcopy-nse-bse-mcx"

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", default=None, help="End date in YYYY-MM-DD format (optional, defaults to --date)")
    return parser.parse_args()

def pick_date(driver, element_id, date_str_yyyymmdd):
    el = driver.find_element(By.ID, element_id)
    driver.execute_script("arguments[0].value = arguments[1];", el, date_str_yyyymmdd)
    driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", el)
    driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", el)
    driver.execute_script("arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));", el)

def wait_for_new_file(download_dir, before_files, timeout=60):
    before_all = set(os.listdir(download_dir))
    deadline = time.time() + timeout
    while time.time() < deadline:
        current_csv = set(f for f in os.listdir(download_dir) if f.endswith("_NSE.csv"))
        new_csv = current_csv - before_files
        if new_csv:
            return ("csv", new_csv.pop())
        current_all = set(os.listdir(download_dir))
        new_files = current_all - before_all
        new_files = {f for f in new_files if not f.endswith(".crdownload")}
        if new_files:
            f = new_files.pop()
            if f.endswith(".zip"):
                return ("zip", f)
        time.sleep(2)
    return (None, None)

def main():
    args = parse_args()
    start_dt = datetime.strptime(args.date, "%Y-%m-%d")
    end_dt   = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else start_dt
    print(f"Downloading NSE bhavcopy for {start_dt.strftime('%d-%m-%Y')} to {end_dt.strftime('%d-%m-%Y')}...")

    before_files = set(f for f in os.listdir(DOWNLOAD_DIR) if f.endswith("_NSE.csv"))

    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
    }
    options.add_experimental_option("prefs", prefs)
    # options.add_argument("--headless")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    wait = WebDriverWait(driver, 20)

    try:
        driver.get(URL)
        time.sleep(3)

        print("Setting start date...")
        pick_date(driver, "start_date", start_dt.strftime("%Y-%m-%d"))
        time.sleep(0.5)

        print("Setting end date...")
        pick_date(driver, "end_date", end_dt.strftime("%Y-%m-%d"))
        time.sleep(0.5)

        # Deselect all except NSE Cash
        segments = {
            "NSE Cash": "bhavcopy_data1",
            "NSE F&O":  "bhavcopy_data2",
            "BSE Cash": "bhavcopy_data3",
            "MCX":      "bhavcopy_data4",
        }
        for name, cb_id in segments.items():
            cb = driver.find_element(By.ID, cb_id)
            is_checked = cb.is_selected()
            if name == "NSE Cash":
                if not is_checked:
                    driver.execute_script("arguments[0].click();", cb)
                    print("Checked NSE Cash")
                else:
                    print("NSE Cash already checked")
            else:
                if is_checked:
                    driver.execute_script("arguments[0].click();", cb)
                    print(f"Unchecked {name}")
        time.sleep(1)

        # Click Submit
        submit_btn = wait.until(EC.element_to_be_clickable((By.ID, "Show")))
        driver.execute_script("arguments[0].click();", submit_btn)
        print("Clicked Submit, waiting for table...")
        time.sleep(4)

        # Click Download
        download_btn = wait.until(EC.element_to_be_clickable((By.ID, "btn_sub")))
        driver.execute_script("arguments[0].click();", download_btn)
        print("Clicked Download, waiting for file...")

        filetype, filename = wait_for_new_file(DOWNLOAD_DIR, before_files, timeout=60)
        if not filename:
            print("ERROR: File did not appear within timeout.")
            sys.exit(1)

        print(f"Downloaded: {filename} ({filetype})")
        src = os.path.join(DOWNLOAD_DIR, filename)

        if filetype == "zip":
            with zipfile.ZipFile(src, "r") as z:
                nse_files = [n for n in z.namelist() if "_NSE.csv" in n or "NSE" in n]
                if not nse_files:
                    print(f"ERROR: No NSE CSV found in zip. Contents: {z.namelist()}")
                    sys.exit(1)

                # Extract ALL NSE files, not just the first one
                for nse_file in nse_files:
                    z.extract(nse_file, DOWNLOAD_DIR)
                    print(f"Extracted: {nse_file}")
                    src_file = os.path.join(DOWNLOAD_DIR, nse_file)
                    dst_file = os.path.join(NSE_DATA_FOLDER, os.path.basename(nse_file))
                    shutil.move(src_file, dst_file)
                    print(f"Moved to: {dst_file}")

            os.remove(src)  # Remove the zip after extracting all files

        else:
            # Single CSV case (filetype == "csv")
            dst = os.path.join(NSE_DATA_FOLDER, filename)
            shutil.move(src, dst)
            print(f"Moved to: {dst}")

    finally:
        driver.quit()

    print("File moved. Watcher will trigger the loader automatically.")

if __name__ == "__main__":
    main()