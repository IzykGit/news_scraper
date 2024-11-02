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
import requests
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
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






    

def sanitize_filename(filename):
    """Sanitize the filename to remove or replace invalid characters."""
    return re.sub(r'[\\/*?:"<>|]', '_', filename)

def load_full_page(driver):
    """Scroll to the bottom of the page to load all dynamically loaded articles."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)  # Adjust the sleep time based on how quickly the site loads new articles
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print("Reached the end of the page; all articles loaded.")
            break
        last_height = new_height

def clean_title(title):
    """Clean up the title by removing the website or publisher name."""
    # Split title by common separators and strip whitespace
    cleaned_title = re.split(r'[-|:]', title)[0].strip()
    return cleaned_title

def extract_main_content(driver):
    """Extract only the main content of the article, avoiding unwanted sections."""
    try:
        # Attempt to locate a main content section
        main_content_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//article | //div[contains(@class, 'content')]"))
        )
        main_content = main_content_element.text
    except NoSuchElementException:
        # Fallback to the full page text if main content section not found
        main_content = driver.find_element(By.TAG_NAME, 'body').text
    
    # Remove unwanted text patterns that may still be included
    main_content = clean_unwanted_text(main_content)
    return main_content

def clean_unwanted_text(content):
    """Clean up unwanted text such as navigation links, pop-ups, or preload ads."""
    # Define unwanted patterns and remove them
    patterns = [
        r"SKIP TO CONTENT", r"SKIP TO SITE INDEX", r"SECTION NAVIGATION", 
        r"SUBSCRIBE FOR \$[0-9]+\/WEEK", r"LOG IN", r"SEARCH"
    ]
    for pattern in patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE).strip()
    return content

def close_popups(driver):
    """Attempt to close common pop-ups like cookie consent and other modal dialogs."""
    try:
        # Look for the 'Accept Cookies' or 'Agree' button
        accept_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept') or contains(text(), 'Agree')]"))
        )
        accept_button.click()
        print("Accepted cookies.")
    except (NoSuchElementException, TimeoutException):
        print("No 'Accept Cookies' button found or it was already accepted.")
    
    # Attempt to close any 'X' pop-up buttons that might appear
    try:
        close_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'X') or @aria-label='Close' or @role='button']"))
        )
        close_button.click()
        print("Closed 'X' popup.")
    except (NoSuchElementException, TimeoutException):
        print("No 'X' close button found.")
    
    # Attempt to find and click a 'Continue' button if it appears
    try:
        continue_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue')]"))
        )
        continue_button.click()
        print("Clicked 'Continue' button.")
    except (NoSuchElementException, TimeoutException):
        print("No 'Continue' button found.")
        

def scrape_articles(driver):
    """Scrape articles from Google News."""
    url = "https://news.google.com/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNREpxT1hvU0FtVnVLQUFQAQ?hl=en-US&gl=US&ceid=US%3Aen"
    json_file_path = "scraped_articles.json"
    
    # Load existing articles data and URLs
    articles_data, existing_urls = load_existing_data(json_file_path)

    logging.info("Starting scraper and loading URL.")
    driver.get(url)
    time.sleep(5)  # Wait for the page to load completely

    close_popups(driver)  # Attempt to close any pop-ups
    logging.info("Loading all articles by scrolling.")
    load_full_page(driver)  # Ensure the full page is loaded with all articles

    i = 0
    while True:
        articles = driver.find_elements(By.XPATH, '//article')

        if i >= len(articles):
            logging.info("No more articles to scrape.")
            break

        try:
            article = articles[i]
            link_element = article.find_element(By.TAG_NAME, 'a')
            link_url = link_element.get_attribute('href')

            # Check if the article URL has already been saved
            if link_url in existing_urls:
                logging.info(f"Article '{link_url}' has already been scraped. Skipping.")
                i += 1
                continue

            # Open article in a new tab, switch to it, and allow it to load
            driver.execute_script(f"window.open('{link_url}', '_blank');")
            driver.switch_to.window(driver.window_handles[1])
            time.sleep(5)  # Allow page to load

            # Get the raw title and clean it
            raw_title = driver.title
            title = clean_title(raw_title)

            # Extract main article content
            full_content = extract_main_content(driver)

            if not full_content:
                logging.info(f"No content found for article {i}. Skipping.")
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                i += 1
                continue

            image_element = driver.find_element(By.XPATH, '//img') if driver.find_elements(By.XPATH, '//img') else None
            image_url = image_element.get_attribute('src') if image_element else ""

            # Extract or set publish date
            try:
                date_element = driver.find_element(By.XPATH, "//time")
                publish_date = date_element.get_attribute("datetime") or date_element.text
            except NoSuchElementException:
                publish_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logging.info(f"Publish date not found; using current date for article {i}.")

            # Extract author information
            try:
                author_element = driver.find_element(By.XPATH, "//*[contains(@class, 'author') or contains(text(), 'By')]")
                author = author_element.text
            except NoSuchElementException:
                author = "Unknown"
                logging.info(f"Author not found; set to 'Unknown' for article {i}.")

            # Generate a unique ID for the article based on its URL
            article_id = hash_url(link_url)

            # Save the article, confirming it's new
            save_article(article_id, title, "", image_url, full_content, publish_date, author)
            logging.info(f"Article '{title}' saved successfully with ID: {article_id}.")

            # Add the new URL to the existing URLs to avoid reprocessing during this run
            existing_urls.add(link_url)

            # Close the tab and switch back to the main window
            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            logging.error(f"Error scraping article {i}: {e}")

        i += 1  # Move to the next article




def hash_url(url):
    """Generate a unique ID based on the URL."""
    return hashlib.md5(url.encode()).hexdigest()

def load_existing_data(file_path):
    """Load existing data from a JSON file and return data and set of URLs."""
    existing_data = {}
    existing_urls = set()
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as json_file:
            try:
                existing_data = json.load(json_file)
                # Extract URLs from existing data to avoid duplicates
                existing_urls = {article["url"] for article in existing_data.values() if "url" in article}
            except json.JSONDecodeError:
                pass  # Handle malformed JSON by returning empty data

    return existing_data, existing_urls

def save_article(article_id, title, description, image_url, full_content, publish_date, author):
    """Save the scraped article information into a single JSON file."""
    json_file_path = "scraped_articles.json"

    # Load existing data from the JSON file
    articles_data, _ = load_existing_data(json_file_path)

    # Ensure articles_data is a dictionary to avoid issues
    if not isinstance(articles_data, dict):
        articles_data = {}

    article_data = {
        "url": article_id,  # Include the URL or identifier here for future reference
        "title": title,
        "description": description,
        "content": full_content,
        "image_url": image_url,
        "publish_date": publish_date,
        "author": author  # Include author in the saved data
    }

    # Add or update the article in the dictionary
    articles_data[article_id] = article_data

    # Write updated data back to the JSON file
    with open(json_file_path, "w", encoding="utf-8") as json_file:
        json.dump(articles_data, json_file, indent=4, ensure_ascii=False)

    print(f"Article '{title}' saved successfully with author '{author}' in the single JSON file.")




if __name__ == "__main__":
    driver = setup_driver()
    try:
        scrape_articles(driver)
    finally:
        driver.quit()
