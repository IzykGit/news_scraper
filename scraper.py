import re
import hashlib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
import json
import logging
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from datetime import datetime


def setup_driver():
    """Set up the Chrome WebDriver."""
    options = Options()
    options.add_argument("--headless")  # Run in headless mode if you don't want a browser UI
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome()
    return driver





# Ensure the `logs` directory exists
log_folder = "logs"
os.makedirs(log_folder, exist_ok=True)

# Define log file paths
current_log_file = os.path.join(log_folder, "scraper.log")
backup_log_file = os.path.join(log_folder, "previous_scrape.log")

# Rotate logs
if os.path.exists(current_log_file):
    if os.path.exists(backup_log_file):
        os.remove(backup_log_file)
    os.rename(current_log_file, backup_log_file)

# Configure logging
logging.basicConfig(
    filename=current_log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def log_progress(message):
    """Log the scraper's progress."""
    logging.info(message)


def load_full_page(driver):
    """Scroll to the bottom of the page to load all dynamically loaded articles."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            logging.info("Reached the end of the page; all articles loaded.")
            break
        last_height = new_height


def clean_title(title):
    """Clean up the title by removing the website or publisher name."""
    return re.split(r'[-|:]', title)[0].strip()


def close_popups(driver):
    """Attempt to close common pop-ups like cookie consent and other modal dialogs."""
    popup_selectors = [
        ("//button[contains(text(), 'Accept') or contains(text(), 'Agree')]", "Accepted cookies"),
        ("//button[contains(text(), 'X') or @aria-label='Close']", "Closed popup"),
        ("//button[contains(text(), 'Continue')]", "Clicked continue button")
    ]
    for selector, success_msg in popup_selectors:
        try:
            button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, selector)))
            button.click()
            logging.info(success_msg)
        except TimeoutException:
            logging.info(f"No popup found for selector: {selector}")


def scrape_articles(driver):
    url = "https://news.google.com/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpxT1hvU0FtVnVLQUFQAQ?hl=en-US&gl=US&ceid=US%3Aen"
    json_file_path = "scraped_articles.json"
    articles_data, existing_urls = load_existing_data(json_file_path)

    log_progress("Starting the scraper and loading URL.")
    driver.get(url)
    time.sleep(5)

    close_popups(driver)
    load_full_page(driver)

    articles = driver.find_elements(By.XPATH, '//article')
    for i, article in enumerate(articles):
        try:
            link_element = article.find_element(By.TAG_NAME, 'a')
            link_url = link_element.get_attribute('href')

            if link_url in existing_urls:
                log_progress(f"Article '{link_url}' has already been scraped. Skipping.")
                continue

            driver.execute_script("window.open(arguments[0]);", link_url)
            driver.switch_to.window(driver.window_handles[1])
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
            log_progress(f"Opened article {link_url}")

            title = clean_title(driver.title)
            full_content = extract_main_content(driver)

            if not full_content:
                log_progress(f"No content found for article {link_url}. Skipping.")
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                continue

            image_element = driver.find_elements(By.XPATH, '//img')
            image_url = image_element[0].get_attribute('src') if image_element else ""

            publish_date = extract_publish_date(driver)
            author = extract_author(driver)

            save_article("Google News", author, title, "", link_url, image_url, publish_date, full_content)
            log_progress(f"Article '{title}' saved successfully.")

            existing_urls.add(link_url)

            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        except WebDriverException as e:
            log_progress(f"Error opening article {i}: {e}")
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])


def extract_main_content(driver):
    """Extracts the main content of the article."""
    try:
        main_content_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//article | //div[contains(@class, 'content')]"))
        )
        return main_content_element.text
    except (NoSuchElementException, TimeoutException):
        logging.info("Main content not found; falling back to body text.")
        return driver.find_element(By.TAG_NAME, 'body').text


def extract_publish_date(driver):
    try:
        date_element = driver.find_element(By.XPATH, "//time")
        return date_element.get_attribute("datetime") or date_element.text
    except NoSuchElementException:
        logging.info("Publish date not found; using current date.")
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_author(driver):
    try:
        author_element = driver.find_element(By.XPATH, "//*[contains(@class, 'author') or contains(text(), 'By')]")
        return author_element.text
    except NoSuchElementException:
        logging.info("Author not found; set to 'Unknown'.")
        return "Unknown"


def hash_url(url):
    return hashlib.md5(url.encode()).hexdigest()


def load_existing_data(file_path):
    """Load existing data from a JSON file and return data and set of URLs."""
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
            existing_urls = {article["url"] for article in data["articles"] if "url" in article}
            return data, existing_urls
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "ok", "totalResults": 0, "articles": []}, set()


def save_article(source_name, author, title, description, url, url_to_image, published_at, content):
    json_file_path = "scraped_articles.json"
    data, _ = load_existing_data(json_file_path)

    article_entry = {
        "source": {"id": None, "name": source_name},
        "author": author,
        "title": title,
        "description": description,
        "url": url,
        "urlToImage": url_to_image,
        "publishedAt": published_at,
        "content": content
    }

    if any(article["url"] == url for article in data["articles"]):
        logging.info(f"Article '{title}' already exists in the JSON. Skipping.")
        return

    data["articles"].append(article_entry)
    data["totalResults"] = len(data["articles"])

    with open(json_file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    driver = setup_driver()
    try:
        scrape_articles(driver)
    finally:
        driver.quit()
