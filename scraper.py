import re
import hashlib
import json
import os
import logging
from datetime import datetime
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

def setup_driver():
    """Set up the Chrome WebDriver."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--log-level=3")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("--window-size=1024x768")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    logging.info("WebDriver initialized.")
    return driver

# Setup logging
log_folder = "logs"
os.makedirs(log_folder, exist_ok=True)
current_log_file = os.path.join(log_folder, "scraper.log")
backup_log_file = os.path.join(log_folder, "previous_scrape.log")

if os.path.exists(current_log_file):
    if os.path.exists(backup_log_file):
        os.remove(backup_log_file)
    os.rename(current_log_file, backup_log_file)

logging.basicConfig(
    filename=current_log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def log_progress(message):
    """Log the scraper's progress."""
    logging.info(message)

def load_existing_data(file_path):
    """Load existing data from a JSON file and return data and set of URLs."""
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
            existing_urls = {article["url"] for article in data.get("articles", []) if "url" in article}
            return data, existing_urls
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "ok", "totalResults": 0, "articles": []}, set()

def hash_url(url):
    """Generate a hash for a URL to uniquely identify it."""
    return hashlib.md5(url.encode()).hexdigest()

def save_article(source_name, author, title, description, url, url_to_image, published_at, content, file_path="scraped_articles.json"):
    """Save a single article to JSON."""
    data, existing_urls = load_existing_data(file_path)

    # Skip saving if article already exists
    if hash_url(url) in existing_urls:
        logging.info(f"Article '{title}' already exists. Skipping.")
        return

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
    
    data["articles"].append(article_entry)
    data["totalResults"] = len(data["articles"])

    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=4, ensure_ascii=False)
    logging.info(f"Article '{title}' saved successfully.")

def clean_title(title):
    """Clean up the title by removing common separators like '-' or ':'."""
    return re.split(r'[-|:]', title)[0].strip()

def close_popups(driver):
    """Close pop-ups like cookie consent using multiple tag types."""
    popup_selectors = [
        ("//button[contains(., 'Accept') or contains(., 'Agree')]", "Accepted cookies (button)"),
        ("//a[contains(., 'Accept') or contains(., 'Agree')]", "Accepted cookies (link)"),
        ("//span[contains(., 'Accept') or contains(., 'Agree')]", "Accepted cookies (span)"),
        ("//button[contains(., 'Close') or @aria-label='Close']", "Closed popup (button)")
    ]

    for selector, success_msg in popup_selectors:
        try:
            button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, selector)))
            button.click()
            logging.info(success_msg)
            time.sleep(0.5)
            return True
        except TimeoutException:
            continue
        except Exception as e:
            logging.error(f"Error clicking popup: {str(e)}")
    return False

def extract_main_content(driver):
    """Extracts the main content of the article."""
    content_selectors = [
        "//article//div[contains(@class, 'content')]", 
        "//article", 
        "//div[contains(@class, 'article-body')]", 
        "//div[contains(@class, 'post-content')]", 
        "//section[contains(@class, 'content')]"
    ]

    for selector in content_selectors:
        try:
            main_content_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, selector))
            )
            content = main_content_element.text.strip()
            if content:
                logging.info(f"Content extracted using selector: {selector}")
                return content
        except (NoSuchElementException, TimeoutException):
            logging.info(f"Selector {selector} did not match any content.")

    logging.warning("Falling back to page source parsing for content extraction.")
    page_content = driver.page_source
    paragraphs = re.findall(r'<p>(.*?)</p>', page_content, re.DOTALL)
    content = "\n".join(paragraph.strip() for paragraph in paragraphs if paragraph.strip())

    if content:
        logging.info("Content extracted using page source fallback.")
        return content
    else:
        logging.error("No content found using any method.")
        return ""

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

def scrape_articles(driver):
    url = "https://www.euronews.com/"
    json_file_path = "scraped_articles.json"
    data, existing_urls = load_existing_data(json_file_path)

    logging.info("Starting the scraper and loading URL.")
    driver.get(url)
    time.sleep(5) 

    close_popups(driver)
    articles = driver.find_elements(By.XPATH, '//article')
    
    for i, article in enumerate(articles):
        try:
            link_element = article.find_element(By.TAG_NAME, 'a')
            link_url = link_element.get_attribute('href')

            if hash_url(link_url) in existing_urls:
                logging.info(f"Article '{link_url}' has already been scraped. Skipping.")
                continue

            driver.execute_script("window.open(arguments[0]);", link_url)
            driver.switch_to.window(driver.window_handles[1])
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
            logging.info(f"Opened article {link_url}")

            title = clean_title(driver.title)
            full_content = extract_main_content(driver)
            if not full_content:
                logging.info(f"No content found for article {link_url}. Skipping.")
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                continue

            image_element = driver.find_elements(By.XPATH, '//img')
            image_url = image_element[0].get_attribute('src') if image_element else ""
            publish_date = extract_publish_date(driver)
            author = extract_author(driver)

            save_article("EuroNews", author, title, "", link_url, image_url, publish_date, full_content, json_file_path)
            existing_urls.add(hash_url(link_url))

            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        except WebDriverException as e:
            logging.error(f"Error opening article {i}: {e}")
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

if __name__ == "__main__":
    driver = setup_driver()
    try:
        scrape_articles(driver)
    finally:
        driver.quit()
        logging.info("WebDriver closed. Scraping session ended.")
