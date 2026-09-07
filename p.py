import sys
import os
import json
import time
import re
import random
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

# Ensure stdout handles UTF-8 encoding on Windows PowerShell / CMD
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def get_installed_chrome_version():
    """
    Detects the installed Chrome major version on Windows or defaults to 150.
    """
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
        version, _ = winreg.QueryValueEx(key, "version")
        major = int(version.split(".")[0])
        return major
    except Exception:
        pass

    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Google\Update\Clients\{8A69D345-D564-463c-AFF1-A69D9E530F96}")
        version, _ = winreg.QueryValueEx(key, "pv")
        major = int(version.split(".")[0])
        return major
    except Exception:
        pass

    return 150

def create_lite_driver(headless=False, use_undetected=True):
    """
    Configures and creates a Chrome WebDriver instance.
    Uses version_main matching the installed Chrome browser (v150).
    """
    chrome_major_version = get_installed_chrome_version()

    if use_undetected and HAS_UC:
        options = uc.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1280,800")
        
        # 1. Try with exact installed Chrome major version (e.g. 150)
        try:
            driver = uc.Chrome(options=options, version_main=chrome_major_version, use_subprocess=True)
            return driver
        except Exception as err1:
            # 2. Try undetected_chromedriver default
            try:
                driver = uc.Chrome(options=options, use_subprocess=True)
                return driver
            except Exception as err2:
                print(f"[*] Notice: undetected_chromedriver version match failed ({err1}). Falling back to standard stealth driver...")

    # Standard Selenium fallback with stealth anti-detection flags
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--window-size=1280,800")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Hide webdriver property via CDP script
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
    except Exception:
        pass
        
    return driver

def click_cloudflare_checkbox(driver):
    """
    Finds Cloudflare / Turnstile checkbox iframe and clicks it like a human.
    """
    try:
        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile'], iframe[title*='Cloudflare'], iframe[src*='challenge']")
        if iframes:
            for iframe in iframes:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", iframe)
                    time.sleep(random.uniform(0.8, 1.5))
                    
                    driver.switch_to.frame(iframe)
                    
                    checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], .mark, #challenge-stage, .ctp-checksum, label.cb-lb")
                    if checkboxes:
                        cb = checkboxes[0]
                        time.sleep(random.uniform(0.5, 1.2))
                        cb.click()
                        print("[+] 👆 Clicked Cloudflare checkbox inside iframe!")
                    else:
                        body = driver.find_element(By.TAG_NAME, "body")
                        body.click()
                        print("[+] 👆 Clicked inside Cloudflare challenge iframe body!")
                    
                    driver.switch_to.default_content()
                    time.sleep(2.5)
                    return True
                except Exception:
                    driver.switch_to.default_content()
        else:
            wrappers = driver.find_elements(By.CSS_SELECTOR, "#turnstile-wrapper, .cf-turnstile, #challenge-stage, .ctp-checkbox-label")
            if wrappers:
                for w in wrappers:
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", w)
                    time.sleep(random.uniform(0.6, 1.2))
                    w.click()
                    print("[+] 👆 Clicked Turnstile checkbox wrapper!")
                    time.sleep(2.5)
                    return True
    except Exception as e:
        driver.switch_to.default_content()
    return False

def check_and_wait_for_captcha(driver, timeout=45):
    """
    Detects Cloudflare / CAPTCHA challenge pages, attempts a human checkbox click,
    and waits for verification to clear.
    """
    start_time = time.time()
    captcha_detected = False
    clicked_once = False

    while time.time() - start_time < timeout:
        title = driver.title.lower()
        page_source = driver.page_source.lower()

        is_challenge = any(keyword in title or keyword in page_source for keyword in [
            "just a moment", "security check", "cloudflare", "challenge-running", "verify you are human", "attention required"
        ])

        if is_challenge:
            if not captcha_detected:
                print("\n[!] 🚨 CAPTCHA / Cloudflare Verification Page Detected!")
                captcha_detected = True

            # Attempt human checkbox click once
            if not clicked_once:
                print("[*] 🔍 Searching for Cloudflare checkbox to click...")
                clicked_once = click_cloudflare_checkbox(driver)
            
            time.sleep(2)
        else:
            if captcha_detected:
                print("[+] ✅ CAPTCHA verification cleared! Continuing scraping...\n")
            break

def human_scroll(driver):
    """
    Simulates gentle human-like scrolling on the page.
    """
    try:
        total_height = int(driver.execute_script("return document.body.scrollHeight"))
        for i in range(1, 4):
            scroll_to = (total_height // 4) * i
            driver.execute_script(f"window.scrollTo(0, {scroll_to});")
            time.sleep(random.uniform(0.5, 1.2))
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass

def format_abstract_text(text):
    """
    Formats abstract text to ensure double spacing between section headings
    and removes unwanted registration lines.
    """
    if not text:
        return "N/A"
    
    # 1. Remove registration lines
    text = re.sub(r'(?i)\bSystematic review registration:.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(?i)\b(?:Trial|PROSPERO|Clinical trial)\s+registration:.*$', '', text, flags=re.MULTILINE)
    
    # 2. Insert double newlines before common section keywords
    pattern = r'(\b(?:Abstract|Background:?|Objective:?|Methods:?|Results:?|Conclusions?:?))'
    formatted = re.sub(pattern, r'\n\n\1', text)
    
    # 3. Clean up excess newlines (>2) and whitespace
    formatted = re.sub(r'\n{3,}', '\n\n', formatted).strip()
    return formatted

def extract_springer_data(driver):
    """
    Extracts structured paper details from Springer Nature (link.springer.com).
    """
    data = {}
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.c-article-title, h1[data-test='article-title']")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    try:
        author_elems = driver.find_elements(By.CSS_SELECTOR, "a[data-test='author-name']")
        authors = [a.text.strip() for a in author_elems if a.text.strip()]
        data["authors"] = authors if authors else []
    except Exception:
        data["authors"] = []

    try:
        time_elem = driver.find_element(By.CSS_SELECTOR, "time[datetime]")
        data["published_date"] = time_elem.text.strip() or time_elem.get_attribute("datetime")
    except Exception:
        data["published_date"] = "N/A"

    try:
        abs_elem = driver.find_element(By.CSS_SELECTOR, "#Abs1-section, #Abs1-content, div[id*='Abs']")
        data["abstract"] = format_abstract_text(abs_elem.text.strip())
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_frontiers_data(driver):
    """
    Extracts structured paper details from Frontiers (frontiersin.org).
    """
    data = {}
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.ArticleDetailsV4__main__title, h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    try:
        author_names = []
        imgs = driver.find_elements(By.CSS_SELECTOR, "a.PeopleListItem img.Avatar__img")
        if imgs:
            for img in imgs:
                alt = img.get_attribute("alt")
                if alt and alt.strip():
                    author_names.append(alt.strip())
        
        if not author_names:
            name_elems = driver.find_elements(By.CSS_SELECTOR, "p.PeopleListItem__name")
            for elem in name_elems:
                name_text = driver.execute_script("return arguments[0].childNodes[0].nodeValue;", elem)
                if name_text and name_text.strip():
                    author_names.append(name_text.strip())
                    
        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    try:
        date_str = "N/A"
        try:
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date']")
            date_str = meta_date.get_attribute("content")
        except Exception:
            date_elem = driver.find_element(By.CSS_SELECTOR, "p.ArticleLayoutHeader__info__journalDate, p[class*='journalDate']")
            text = date_elem.text.strip()
            if "," in text:
                date_str = text.split(",")[-1].strip()
            else:
                date_str = text
        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    try:
        abs_elem = driver.find_element(By.CSS_SELECTOR, "div#h1, div[id='h1']")
        paragraphs = abs_elem.find_elements(By.CSS_SELECTOR, "p, h2, h3")
        if paragraphs:
            lines = [p.text.strip() for p in paragraphs if p.text.strip()]
            formatted_lines = []
            i = 0
            while i < len(lines):
                line = lines[i]
                if (line.endswith(":") or line in ["Abstract", "Background:", "Objective:", "Methods:", "Results:", "Conclusions:"]) and i + 1 < len(lines) and not lines[i+1].endswith(":"):
                    formatted_lines.append(f"{line} {lines[i+1]}")
                    i += 2
                else:
                    formatted_lines.append(line)
                    i += 1
            raw_abstract = "\n\n".join(formatted_lines)
            data["abstract"] = format_abstract_text(raw_abstract)
        else:
            data["abstract"] = format_abstract_text(abs_elem.text.strip())
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_cell_data(driver):
    """
    Extracts structured paper details from Cell Press / Heliyon (cell.com).
    """
    data = {}
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1[property='name'], h1.article-header__title, h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    try:
        author_names = []
        author_elems = driver.find_elements(By.CSS_SELECTOR, "div.contributors span[property='author']")
        for elem in author_elems:
            try:
                given = elem.find_element(By.CSS_SELECTOR, "span[property='givenName']").text.strip()
                family = elem.find_element(By.CSS_SELECTOR, "span[property='familyName']").text.strip()
                name = f"{given} {family}".strip()
                if name and name not in author_names:
                    author_names.append(name)
            except Exception:
                pass
        
        if not author_names:
            links = driver.find_elements(By.CSS_SELECTOR, "div.contributors a[data-db-target-for]")
            for a in links:
                txt = a.text.strip()
                if txt and txt not in author_names:
                    author_names.append(txt)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(By.CSS_SELECTOR, "span.meta-panel__onlineDate")
            date_str = date_elem.text.strip()
        except Exception:
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_online_date'], meta[name='citation_publication_date']")
            date_str = meta_date.get_attribute("content")
        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    try:
        abs_elem = driver.find_element(By.CSS_SELECTOR, "section#author-abstract, section[property='abstract'], div.article-tools__abstract, div.abstract")
        sections = abs_elem.find_elements(By.CSS_SELECTOR, "section, div[id*='abssec'], p")
        if sections:
            lines = [sec.text.strip() for sec in sections if sec.text.strip()]
            raw_abstract = "\n\n".join(lines)
            data["abstract"] = format_abstract_text(raw_abstract)
        else:
            data["abstract"] = format_abstract_text(abs_elem.text.strip())
    except Exception:
        data["abstract"] = "N/A"

    return data

def load_links_from_json(json_path):
    """
    Reads a JSON file and extracts paper metadata.
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
    Opens extracted links sequentially using Undetected Browser & Human Checkbox Clicker.
    """
    if not link_items:
        print("[!] No links to process.")
        return

    total = len(link_items)
    if max_count:
        link_items = link_items[:max_count]

    print(f"\n==================================================================")
    print(f"[*] STARTING UNDETECTED BROWSER SCRAPPER (Links: {len(link_items)} / Total: {total})")
    print(f"[*] Mode: {'Headless (Silent)' if headless else 'Visible Window (GUI - Human Clicker Enabled)'}")
    print(f"==================================================================\n")

    driver = create_lite_driver(headless=headless, use_undetected=True)

    results = []
    try:
        for item in link_items:
            url = item["link"]
            parsed_domain = urlparse(url).netloc.lower()
            
            print(f"------------------------------------------------------------------")
            print(f"[+] ITEM [{item['index'] + 1}/{total}]")
            print(f"[+] Target URL: {url}")
            print(f"------------------------------------------------------------------")
            
            try:
                print(f"[*] Navigating to URL with Undetected Browser...")
                start_time = time.time()
                driver.get(url)
                
                # Check for Cloudflare / CAPTCHA and simulate human click on checkbox
                check_and_wait_for_captcha(driver)
                
                # Simulate human interaction (scroll)
                human_scroll(driver)

                elapsed = time.time() - start_time
                print(f"[+] Loaded in {elapsed:.2f} seconds!")

                scraped_data = {}
                
                # Domain-Specific Parsers
                if "link.springer.com" in parsed_domain:
                    print(f"[*] Springer Domain Detected -> Extracting Springer Article Elements...")
                    scraped_data = extract_springer_data(driver)
                    
                    print(f"\n--- [ Springer Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "frontiersin.org" in parsed_domain:
                    print(f"[*] Frontiersin.org Domain Detected -> Extracting Frontiers Article Elements...")
                    scraped_data = extract_frontiers_data(driver)
                    
                    print(f"\n--- [ Frontiers Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "cell.com" in parsed_domain:
                    print(f"[*] Cell.com Domain Detected -> Extracting Cell Press Article Elements...")
                    scraped_data = extract_cell_data(driver)
                    
                    print(f"\n--- [ Cell Press Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                else:
                    print(f"[+] Page Title : {driver.title}")
                    print(f"[+] Final URL  : {driver.current_url}")

                if wait_time > 0 and not headless:
                    print(f"[*] Keeping browser visible for {wait_time}s inspection...")
                    time.sleep(wait_time)

                results.append({
                    "url": url,
                    "scraped_data": scraped_data,
                    "status": "success"
                })

            except Exception as ex:
                print(f"[!] Failed to load {url}: {ex}")
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": str(ex)
                })
    finally:
        print(f"\n==================================================================")
        print(f"[*] SCRAPING COMPLETED | Closing Browser Session")
        print(f"==================================================================\n")
        try:
            driver.quit()
        except Exception:
            pass

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
