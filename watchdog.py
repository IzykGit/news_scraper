import os
import time
import subprocess
from datetime import datetime, timedelta
import logging

# Define log paths
log_folder = "logs"
LOG_FILE = os.path.join(log_folder, "scraper.log")  # Updated path for scraper log
WATCHDOG_LOG_FILE = os.path.join(log_folder, "watchdog.log")  # Updated path for watchdog log
SCRAPER_COMMAND = ["python", "scraper.py"]
TIMEOUT = 300  # Restart if no activity for 5 minutes

# Ensure `scraped_logs` folder exists
os.makedirs(log_folder, exist_ok=True)

# Configure logging to use `watchdog.log` in `scraped_logs`
logging.basicConfig(
    filename=WATCHDOG_LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def last_log_time():
    """Return the last modified time of the scraper log file."""
    if os.path.exists(LOG_FILE):
        return datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
    return None

def start_scraper():
    """Start the scraper process."""
    logging.info("Starting scraper.")
    return subprocess.Popen(SCRAPER_COMMAND)

def monitor_scraper():
    """Monitor and restart scraper based on log activity."""
    scraper_process = start_scraper()

    while True:
        time.sleep(10)  # Check every 10 seconds
        last_modified = last_log_time()
        
        # Check if the log file has recent entries
        if last_modified and (datetime.now() - last_modified) > timedelta(seconds=TIMEOUT):
            logging.warning("No recent log activity. Restarting scraper.")
            scraper_process.terminate()
            scraper_process.wait()
            scraper_process = start_scraper()

        elif scraper_process.poll() is not None:
            logging.warning("Scraper process stopped unexpectedly. Restarting.")
            scraper_process = start_scraper()

if __name__ == "__main__":
    try:
        monitor_scraper()
    except KeyboardInterrupt:
        logging.info("Watchdog stopped by user.")
