import sys
import os
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def create_lite_driver(headless=False, disable_images=False):
    """
    Configures and creates a Selenium Chrome WebDriver instance.
    """
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    # Resource & stability options
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    
    prefs = {
        "profile.managed_default_content_settings.images": 2 if disable_images else 1,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    options.page_load_strategy = 'eager'
    options.add_argument("--window-size=1280,800")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    return driver

def load_links_from_json(json_path):
    """
    Reads a JSON file (e.g. input.txt or paper.txt) and extracts the 'link' property.
    Supports single JSON objects, JSON lists, or line-delimited JSON objects.
    """
    if not os.path.exists(json_path):
        print(f"[!] File not found: {json_path}")
        return []

    links = []
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        if not content:
            return []

        # Try parsing as full JSON first
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for idx, item in enumerate(data):
                    if isinstance(item, dict) and "link" in item:
                        links.append({
                            "index": idx,
                            "title": item.get("title", "No Title"),
                            "link": item["link"]
                        })
            elif isinstance(data, dict) and "link" in data:
                links.append({
                    "index": 0,
                    "title": data.get("title", "No Title"),
                    "link": data["link"]
                })
        except json.JSONDecodeError:
            # Fallback: line-by-line JSON parsing if file contains raw string blocks
            for idx, line in enumerate(content.splitlines()):
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict) and "link" in item:
                            links.append({
                                "index": idx,
                                "title": item.get("title", "No Title"),
                                "link": item["link"]
                            })
                    except Exception:
                        pass

        return links
    except Exception as e:
        print(f"[!] Error reading file {json_path}: {e}")
        return []

def process_links(link_items, headless=False, disable_images=False, wait_time=5, max_count=None):
    """
    Opens extracted links sequentially using the Selenium browser.
    """
    if not link_items:
        print("[!] No links to process.")
        return

    total = len(link_items)
    if max_count:
        link_items = link_items[:max_count]

    print(f"[*] Starting browser session for {len(link_items)} link(s) (Total in file: {total})...")
    driver = create_lite_driver(headless=headless, disable_images=disable_images)

    results = []
    try:
        for item in link_items:
            url = item["link"]
            title = item.get("title", "Unknown")
            print(f"\n----------------------------------------")
            print(f"[*] [{item['index'] + 1}/{total}] Title: {title}")
            print(f"[*] Opening Link: {url}")
            
            try:
                start_time = time.time()
                driver.get(url)
                elapsed = time.time() - start_time
                
                print(f"[+] Loaded in {elapsed:.2f}s | Page Title: '{driver.title}'")
                print(f"[+] Current URL: {driver.current_url}")
                
                if wait_time > 0:
                    print(f"[*] Pausing for {wait_time} seconds for visual inspection...")
                    time.sleep(wait_time)

                results.append({
                    "title": title,
                    "url": url,
                    "actual_title": driver.title,
                    "final_url": driver.current_url,
                    "status": "success"
                })

            except Exception as ex:
                print(f"[!] Failed to load {url}: {ex}")
                results.append({
                    "title": title,
                    "url": url,
                    "status": "failed",
                    "error": str(ex)
                })
    finally:
        print("\n[*] Closing browser session...")
        driver.quit()

    return results

if __name__ == "__main__":
    is_headless = "--headless" in sys.argv
    
    # Filter out flags from args
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    
    input_target = args[0] if args else None
    
    if input_target and (input_target.startswith("http://") or input_target.startswith("https://")):
        process_links([{"index": 0, "title": "Direct URL", "link": input_target}], headless=is_headless, disable_images=False, wait_time=5)
    else:
        # Determine target file (input_target -> input.txt -> paper.txt)
        file_to_open = None
        if input_target and os.path.isfile(input_target):
            file_to_open = input_target
        elif os.path.isfile("input.txt"):
            file_to_open = "input.txt"
        elif os.path.isfile("paper.txt"):
            file_to_open = "paper.txt"
            
        if file_to_open:
            print(f"[*] Reading links from JSON file: {file_to_open}")
            link_items = load_links_from_json(file_to_open)
            print(f"[*] Found {len(link_items)} link(s) in {file_to_open}")
            process_links(link_items, headless=is_headless, disable_images=False, wait_time=5)
        else:
            print("[!] Please provide a valid URL or JSON file path containing links (e.g. input.txt).")
