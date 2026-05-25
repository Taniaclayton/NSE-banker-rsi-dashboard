"""
NSE Auto-loader Watcher
========================
Watches your bhavcopy folder for new *_NSE.csv (or NSE_*.csv) files.
When a new file appears, automatically runs the NSE loader to
compute signals and insert into MySQL.

Run once and leave it open in a terminal:
    python nse_watcher.py

Requirements:
    pip install watchdog

Edit LOADER_SCRIPT and WATCH_FOLDER below to match your paths.
"""

import sys
import time
import subprocess
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── EDIT THESE ────────────────────────────────────────────────────────────────
WATCH_FOLDER  = r"D:\Trading\nse dashboard\banker dashboard\data"
LOADER_SCRIPT = r"D:\Trading\nse_to_mysql_with_banker_signal.py"
# ─────────────────────────────────────────────────────────────────────────────

import os
os.environ["PYTHONIOENCODING"] = "utf-8"
PYTHON  = r"D:\Programs\python\python.exe"   # same Python that runs this script
running = False                               # prevent overlapping runs


class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        global running
        path = Path(event.src_path)

        if event.is_directory:
            return
        # Match both YYYYMMDD_NSE.csv and NSE_YYYYMMDD.csv
        name = path.name
        if not ((name.endswith("_NSE.csv") or name.startswith("NSE_")) and path.suffix == ".csv"):
            return
        if running:
            print(f"[nse_watcher] Still processing previous file, skipping {name}")
            return

        print(f"\n[nse_watcher] New file detected: {name}")
        _run_loader()

    def on_moved(self, event):
        """Also catches files moved/copied into the folder."""
        self.on_created(type("E", (), {
            "src_path": event.dest_path,
            "is_directory": event.is_directory,
        })())


def _run_loader():
    global running
    running = True
    print("[nse_watcher] Running NSE loader...")
    try:
        result = subprocess.run(
            [PYTHON, LOADER_SCRIPT],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("[nse_watcher] ✓ Loader finished successfully.")
            out = result.stdout
            print(out[-800:] if len(out) > 800 else out)
        else:
            print("[nse_watcher] ✗ Loader failed:")
            err = result.stderr
            print(err[-800:] if len(err) > 800 else err)
    except Exception as e:
        print(f"[nse_watcher] Error running loader: {e}")
    finally:
        running = False


if __name__ == "__main__":
    watch_path = Path(WATCH_FOLDER)
    if not watch_path.exists():
        print(f"ERROR: Watch folder not found: {WATCH_FOLDER}")
        sys.exit(1)

    print(f"[nse_watcher] Watching : {WATCH_FOLDER}")
    print(f"[nse_watcher] Loader   : {LOADER_SCRIPT}")
    print(f"[nse_watcher] Waiting for new *_NSE.csv / NSE_*.csv files... (Ctrl+C to stop)\n")

    observer = Observer()
    observer.schedule(NewFileHandler(), str(watch_path), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[nse_watcher] Stopped.")
    observer.join()
