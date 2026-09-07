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
    uc.Chrome.__del__ = lambda self: None
except ImportError:
    HAS_UC = False

# Ensure stdout handles UTF-8 encoding on Windows PowerShell / CMD
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def get_installed_chrome_version():
    """
    Detects installed Chrome major version on Windows or defaults to 150.
    """
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
        version, _ = winreg.QueryValueEx(key, "version")
        return int(version.split(".")[0])
    except Exception:
        pass
    return 150

def create_lite_driver(headless=False):
    """
    Creates a fast, lightweight, resource-optimized Selenium Chrome WebDriver.
    Used for standard fast domains (Springer, Frontiers, MDPI, etc.).
    """
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
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    
    prefs = {
        "profile.managed_default_content_settings.images": 2, # Disable images for speed
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    options.page_load_strategy = 'eager'
    options.add_argument("--window-size=1280,800")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def create_humanoid_driver(headless=False):
    """
    Creates an Undetected Chrome Driver specifically for Cell.com (CAPTCHA protected).
    """
    chrome_major_version = get_installed_chrome_version()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

    if HAS_UC:
        options = uc.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--start-maximized")
        options.add_argument(f"user-agent={user_agent}")
        options.add_argument("--lang=en-US,en")
        
        try:
            driver = uc.Chrome(options=options, version_main=chrome_major_version, use_subprocess=True)
            return driver
        except Exception:
            try:
                driver = uc.Chrome(options=options, use_subprocess=True)
                return driver
            except Exception:
                pass

    return create_lite_driver(headless=headless)

def humanoid_mouse_and_scroll(driver):
    """
    Simulates gentle human-like mouse movements and natural scrolling for Cell.com.
    """
    try:
        actions = ActionChains(driver)
        actions.move_by_offset(random.randint(10, 50), random.randint(10, 50)).perform()
        time.sleep(random.uniform(0.5, 1.2))
        
        total_height = int(driver.execute_script("return document.body.scrollHeight"))
        if total_height > 500:
            scroll_target = random.randint(200, min(800, total_height))
            driver.execute_script(f"window.scrollTo({{top: {scroll_target}, behavior: 'smooth'}});")
            time.sleep(random.uniform(1.0, 1.5))
            driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
    except Exception:
        pass

def format_abstract_text(text):
    """
    Formats abstract text cleanly:
    - Excludes trailing Keywords, Graphical Abstracts, and Registration metadata lines.
    - Adds double spacing before section headings.
    """
    if not text:
        return "N/A"
    
    # 1. Strip out Keywords / Graphical Abstract / Registration sections
    text = re.sub(r'(?is)\bKeywords?:.*$', '', text)
    text = re.sub(r'(?is)\bKey\s+words?:.*$', '', text)
    text = re.sub(r'(?is)\bGraphical\s+Abstract.*$', '', text)
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
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1[property='name'], h1.article-header__title, h1.article-title, h1")
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
        abs_elem = driver.find_element(By.CSS_SELECTOR, "section#author-abstract, section[property='abstract'], div.article-tools__abstract, div.abstract, #abstract")
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

def extract_mdpi_data(driver):
    """
    Extracts structured paper details from MDPI (mdpi.com).
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.title, h1[itemprop='name'], h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elems = driver.find_elements(By.CSS_SELECTOR, "div.art-authors div.profile-card-drop")
        for elem in author_elems:
            raw_name = driver.execute_script(
                "return arguments[0].childNodes[0] ? arguments[0].childNodes[0].nodeValue : arguments[0].innerText;", elem
            )
            if not raw_name or not raw_name.strip():
                raw_name = elem.text.splitlines()[0] if elem.text else ""
            clean_name = raw_name.strip()
            if clean_name and clean_name not in author_names:
                author_names.append(clean_name)
                
        if not author_names:
            links = driver.find_elements(By.CSS_SELECTOR, "div.art-authors span.inlineblock")
            for l in links:
                txt = l.text.splitlines()[0].replace("by", "").replace(",", "").strip()
                if txt and txt not in author_names:
                    author_names.append(txt)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Date
    try:
        date_str = "N/A"
        try:
            spans = driver.find_elements(By.CSS_SELECTOR, "div.pubhistory span, div.bib-identity span")
            for s in spans:
                if "Published:" in s.text:
                    date_str = s.text.replace("Published:", "").strip()
                    break
        except Exception:
            pass

        if date_str == "N/A":
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date']")
            date_str = meta_date.get_attribute("content")

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        abs_elem = driver.find_element(By.CSS_SELECTOR, "div.html-p, section.html-abstract, #html-abstract, section.art-abstract, div.art-abstract, div.abstract_div")
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

def process_links(link_items, headless=False, disable_images=False, max_count=None):
    """
    Opens extracted links sequentially:
    - Uses Undetected Humanoid mode ONLY for cell.com (CAPTCHA protected).
    - Uses fast, lightweight driver for all other domains (Springer, Frontiers, MDPI, etc.).
    """
    if not link_items:
        print("[!] No links to process.")
        return

    total = len(link_items)
    if max_count:
        link_items = link_items[:max_count]

    print(f"\n==================================================================")
    print(f"[*] STARTING MULTI-DOMAIN BROWSER SCRAPPER (Target Links: {len(link_items)})")
    print(f"==================================================================\n")

    results = []
    current_driver = None
    current_driver_type = None  # 'lite' or 'cell_humanoid'

    try:
        for item in link_items:
            url = item["link"]
            parsed_domain = urlparse(url).netloc.lower()
            needs_cell_humanoid = "cell.com" in parsed_domain

            # Switch driver if required domain mode changes
            required_type = "cell_humanoid" if needs_cell_humanoid else "lite"
            if current_driver_type != required_type:
                if current_driver:
                    try:
                        current_driver.quit()
                    except Exception:
                        pass
                
                if required_type == "cell_humanoid":
                    print("[*] 🛡️ Initializing Undetected Humanoid Browser (Cell.com CAPTCHA Mode)...")
                    current_driver = create_humanoid_driver(headless=headless)
                else:
                    print("[*] ⚡ Initializing Fast Lite Browser (Springer/Frontiers/MDPI Mode)...")
                    current_driver = create_lite_driver(headless=headless)
                
                current_driver_type = required_type

            print(f"------------------------------------------------------------------")
            print(f"[+] ITEM [{item['index'] + 1}/{total}]")
            print(f"[+] Target URL: {url}")
            print(f"------------------------------------------------------------------")
            
            try:
                start_time = time.time()
                current_driver.get(url)
                
                # Extra humanoid delay & mouse move ONLY for cell.com
                if needs_cell_humanoid:
                    time.sleep(4)
                    humanoid_mouse_and_scroll(current_driver)
                    time.sleep(3)
                else:
                    time.sleep(1) # Fast DOM load for other domains

                elapsed = time.time() - start_time
                print(f"[+] Loaded in {elapsed:.2f} seconds!")

                scraped_data = {}
                
                # Domain-Specific Parsers
                if "link.springer.com" in parsed_domain:
                    print(f"[*] Springer Domain Detected -> Extracting Springer Article Elements...")
                    scraped_data = extract_springer_data(current_driver)
                    
                    print(f"\n--- [ Springer Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "frontiersin.org" in parsed_domain:
                    print(f"[*] Frontiersin.org Domain Detected -> Extracting Frontiers Article Elements...")
                    scraped_data = extract_frontiers_data(current_driver)
                    
                    print(f"\n--- [ Frontiers Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "cell.com" in parsed_domain:
                    print(f"[*] Cell.com Domain Detected -> Extracting Cell Press Article Elements...")
                    scraped_data = extract_cell_data(current_driver)
                    
                    print(f"\n--- [ Cell Press Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "mdpi.com" in parsed_domain:
                    print(f"[*] MDPI Domain Detected -> Extracting MDPI Article Elements...")
                    scraped_data = extract_mdpi_data(current_driver)
                    
                    print(f"\n--- [ MDPI Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                else:
                    print(f"[+] Page Title : {current_driver.title}")
                    print(f"[+] Final URL  : {current_driver.current_url}")

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
        if current_driver:
            try:
                current_driver.quit()
            except Exception:
                pass

    return results

if __name__ == "__main__":
    is_headless = "--headless" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    input_target = args[0] if args else None
    
    if input_target and (input_target.startswith("http://") or input_target.startswith("https://")):
        process_links([{"index": 0, "title": "Direct URL", "link": input_target}], headless=is_headless, disable_images=False)
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
            process_links(link_items, headless=is_headless, disable_images=False)
        else:
            print("[!] Please provide a valid URL or JSON file path containing links (e.g. input.txt).")
