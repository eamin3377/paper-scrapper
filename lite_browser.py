import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def create_lite_driver(headless=True, disable_images=True):
    """
    Configures and creates a lightweight Selenium Chrome WebDriver instance.
    """
    options = Options()

    # Run in headless mode if specified
    if headless:
        options.add_argument("--headless=new")

    # Resource reduction & performance optimization flags
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    
    # Custom prefs to disable images and notifications
    prefs = {
        "profile.managed_default_content_settings.images": 2 if disable_images else 1,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    # Page load strategy to 'eager' (DOM ready, don't wait for full image/resource load)
    options.page_load_strategy = 'eager'

    # Set window size for standard rendering
    options.add_argument("--window-size=1280,720")

    # Use webdriver_manager to get ChromeDriver executable
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    return driver

def open_url(url, headless=True, disable_images=True, wait_time=2):
    """
    Opens a given URL using the lite browser and returns basic page details.
    """
    print(f"[*] Launching lite browser (Headless={headless}, Images Disabled={disable_images})...")
    driver = create_lite_driver(headless=headless, disable_images=disable_images)
    
    try:
        print(f"[*] Navigating to: {url}")
        start_time = time.time()
        driver.get(url)
        elapsed = time.time() - start_time
        
        print(f"[+] Loaded in {elapsed:.2f} seconds")
        print(f"[+] Page Title: {driver.title}")
        print(f"[+] Current URL: {driver.current_url}")
        
        if wait_time > 0:
            time.sleep(wait_time)
            
        page_source_snippet = driver.page_source[:500]
        return {
            "title": driver.title,
            "url": driver.current_url,
            "snippet": page_source_snippet
        }
    finally:
        print("[*] Closing browser session...")
        driver.quit()

if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = open_url(target_url)
    print("\n--- Result Summary ---")
    print(f"Title: {result['title']}")
    print(f"URL: {result['url']}")
