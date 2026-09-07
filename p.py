import sys
import os
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# Ensure stdout handles UTF-8 encoding on Windows PowerShell / CMD
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def create_lite_driver(headless=False, disable_images=False):
    """
    Configures and creates a Selenium Chrome WebDriver instance.
    """
    options = Options()

    if headless:
        options.add_argument("--headless=new")

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
    Reads a JSON file and extracts paper metadata including title, link, authors, etc.
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

        def extract_item_info(idx, item):
            if isinstance(item, dict) and "link" in item:
                return {
                    "index": idx,
                    "title": item.get("title", "No Title"),
                    "link": item["link"],
                    "document_link": item.get("documentLink", "N/A"),
                    "authors": item.get("authors", "N/A"),
                    "source": item.get("source", "N/A"),
                    "year": item.get("year", "N/A"),
                    "citations": item.get("citations", "N/A")
                }
            return None

        try:
            data = json.loads(content)
            if isinstance(data, list):
                for idx, item in enumerate(data):
                    info = extract_item_info(idx, item)
                    if info:
                        links.append(info)
            elif isinstance(data, dict):
                info = extract_item_info(0, data)
                if info:
                    links.append(info)
        except json.JSONDecodeError:
            for idx, line in enumerate(content.splitlines()):
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        info = extract_item_info(idx, item)
                        if info:
                            links.append(info)
                    except Exception:
                        pass

        return links
    except Exception as e:
        print(f"[!] Error reading file {json_path}: {e}")
        return []

def process_links(link_items, headless=False, disable_images=False, wait_time=5, max_count=None):
    """
    Opens extracted links sequentially and outputs detailed progress and scraped information to terminal.
    """
    if not link_items:
        print("[!] No links to process.")
        return

    total = len(link_items)
    if max_count:
        link_items = link_items[:max_count]

    print(f"\n==================================================================")
    print(f"[*] STARTING BROWSER SCRAPPER (Target Links: {len(link_items)} / Total: {total})")
    print(f"[*] Mode: {'Headless (Silent)' if headless else 'Visible Window (GUI)'}")
    print(f"==================================================================\n")

    driver = create_lite_driver(headless=headless, disable_images=disable_images)

    results = []
    try:
        for item in link_items:
            url = item["link"]
            title = item.get("title", "Unknown")
            print(f"------------------------------------------------------------------")
            print(f"[+] ITEM [{item['index'] + 1}/{total}]")
            print(f"[+] Title     : {title}")
            print(f"[+] Authors   : {item.get('authors')}")
            print(f"[+] Source    : {item.get('source')} ({item.get('year')})")
            print(f"[+] Target URL: {url}")
            if item.get("document_link") != "N/A":
                print(f"[+] PDF Link  : {item.get('document_link')}")
            print(f"------------------------------------------------------------------")
            
            try:
                print(f"[*] Navigating to URL...")
                start_time = time.time()
                driver.get(url)
                elapsed = time.time() - start_time
                
                print(f"[+] Loaded successfully in {elapsed:.2f} seconds!")
                print(f"[+] Page Title : {driver.title}")
                print(f"[+] Final URL  : {driver.current_url}")
                
                # Extract main heading (H1) if present
                h1_text = "N/A"
                try:
                    h1_elem = driver.find_element(By.TAG_NAME, "h1")
                    h1_text = h1_elem.text.strip().replace("\n", " ")
                except Exception:
                    pass
                print(f"[+] H1 Heading : {h1_text}")

                # Extract meta description or abstract snippet
                meta_desc = "N/A"
                try:
                    meta_elem = driver.find_element(By.XPATH, "//meta[@name='description' or @property='og:description']")
                    meta_desc = meta_elem.get_attribute("content")
                    if meta_desc and len(meta_desc) > 150:
                        meta_desc = meta_desc[:150] + "..."
                except Exception:
                    pass
                print(f"[+] Meta Desc  : {meta_desc}")

                if wait_time > 0 and not headless:
                    print(f"[*] Keeping browser visible for {wait_time}s inspection...")
                    time.sleep(wait_time)

                results.append({
                    "title": title,
                    "url": url,
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
        print(f"\n==================================================================")
        print(f"[*] SCRAPING COMPLETED | Closing Browser Session")
        print(f"==================================================================\n")
        driver.quit()

    return results

if __name__ == "__main__":
    is_headless = "--headless" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    input_target = args[0] if args else None
    
    if input_target and (input_target.startswith("http://") or input_target.startswith("https://")):
        process_links([{"index": 0, "title": "Direct URL", "link": input_target}], headless=is_headless, disable_images=False, wait_time=5)
    else:
        file_to_open = None
        if input_target and os.path.isfile(input_target):
            file_to_open = input_target
        elif os.path.isfile("input.txt"):
            file_to_open = "input.txt"
        elif os.path.isfile("paper.txt"):
            file_to_open = "paper.txt"
            
        if file_to_open:
            print(f"[*] Reading input file: {file_to_open}")
            link_items = load_links_from_json(file_to_open)
            print(f"[*] Found {len(link_items)} link(s) to process.")
            process_links(link_items, headless=is_headless, disable_images=False, wait_time=5)
        else:
            print("[!] Please provide a valid URL or JSON file path containing links (e.g. input.txt).")
