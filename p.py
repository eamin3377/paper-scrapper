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
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    options.page_load_strategy = 'eager'
    options.add_argument("--window-size=1280,800")

    try:
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        # Selenium 4.6+ includes native Selenium Manager which handles chromedriver automatically
        driver = webdriver.Chrome(options=options)
    return driver

def create_humanoid_driver(headless=False):
    """
    Creates an Undetected Chrome Driver specifically for Cell.com & Wiley (CAPTCHA protected).
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
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=en-US,en")
        
        # Use a persistent browser profile directory so human verification and cookies are remembered
        profile_dir = os.path.join(os.path.expanduser("~"), ".scrapper_chrome_profile")
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.page_load_strategy = 'normal'
        
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

def wait_for_captcha_and_content(driver, selectors, timeout=45):
    """
    Waits naturally as a human browser. If a verification / Cloudflare page appears,
    it gives the user plenty of time (with live countdown/prompt in console) to complete
    the verification manually or allow Turnstile to resolve naturally.
    As soon as verification clears and article content appears, it proceeds immediately.
    """
    start_time = time.time()
    notified_user = False
    last_print_time = 0

    while time.time() - start_time < timeout:
        try:
            title = driver.title.lower()
            is_verification = (
                "are you a robot" in title or 
                "just a moment" in title or 
                "cloudflare" in title or 
                "attention required" in title or
                "security check" in title or
                "verify you are human" in title or
                "verifying" in title or
                driver.find_elements(By.CSS_SELECTOR, "iframe[src*='challenges.cloudflare.com'], div#challenge-stage, div.cf-turnstile")
            )

            if is_verification:
                curr_now = time.time()
                remaining = int(timeout - (curr_now - start_time))
                if not notified_user or (curr_now - last_print_time > 8):
                    print(f"[*] ⏳ Security / Human Verification screen detected! Please complete the verification in the browser window if prompted (Waiting {remaining}s)...")
                    notified_user = True
                    last_print_time = curr_now

                time.sleep(1.0)
                continue

            # If verification is no longer showing, check for target content
            for selector in selectors:
                elems = driver.find_elements(By.CSS_SELECTOR, selector)
                if elems and any(e.text.strip() for e in elems):
                    if notified_user:
                        print("[*] ✅ Verification passed and article content detected!")
                    return True
        except Exception:
            pass
        time.sleep(0.5)

    if notified_user:
        print("[!] Verification wait timed out. Proceeding to extract available DOM / Crossref metadata.")
    return False

def humanoid_mouse_and_scroll(driver):
    """
    Simulates gentle human-like mouse movements and natural scrolling for CAPTCHA protected domains.
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
    - Slices strictly starting from 'Abstract' or body text.
    - Excludes trailing Keywords, Graphical Abstracts, and UI metadata lines.
    - Adds double spacing before section headings.
    """
    if not text:
        return "N/A"
    
    # Slice text starting from 'Abstract' if present
    if "Abstract" in text:
        text = text[text.find("Abstract"):]

    # 1. Strip out UI buttons/navigation text & Keywords / Graphical Abstract / Registration sections
    text = re.sub(r'(?i)\b(?:first_page|settings|Order Article Reprints|Open Access|Download|keyboard_arrow_down|Browse Figures|Versions|Notes)\b', '', text)
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

def clean_title_text(text):
    """
    Removes MDPI UI badges like 'first_page', 'settings', 'Order Article Reprints', 'Open Access', 'Review', etc. from title.
    """
    if not text:
        return ""
    cleaned = re.sub(r'^(?:first_page|settings|Order\s+Article\s+Reprints|Open\s+AccessReview|Open\s+Access|Review|Article|Communication|Editorial)\s*', '', text, flags=re.IGNORECASE).strip()
    return cleaned

def extract_sciencedirect_data(driver):
    """
    Extracts structured paper details from ScienceDirect (sciencedirect.com).
    - Title: span.title-text, h1.title-text, h1
    - Authors: div.author-group span.given-name + span.surname (e.g. Anjana Patney, Ravindra Patel)
    - Publication Date: div.text-xs (regex match 4-digit year like 2025) / meta citation_publication_date
    - Abstract: div.abstract#abs0001, div#abss0001
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "span.title-text, h1.title-text, h1[class*='title'], h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_buttons = driver.find_elements(By.CSS_SELECTOR, "div.author-group button, div#author-group button")
        for btn in author_buttons:
            try:
                given = btn.find_element(By.CSS_SELECTOR, "span.given-name").text.strip()
                surname = btn.find_element(By.CSS_SELECTOR, "span.surname").text.strip()
                full_name = f"{given} {surname}".strip()
                if full_name and full_name not in author_names:
                    author_names.append(full_name)
            except Exception:
                pass

        if not author_names:
            spans = driver.find_elements(By.CSS_SELECTOR, "span.react-xocs-alternative-link")
            for s in spans:
                raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", s)
                clean_name = raw_name.strip() if raw_name else ""
                if clean_name and clean_name not in author_names:
                    author_names.append(clean_name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Date / Year
    try:
        date_str = "N/A"
        try:
            vol_div = driver.find_element(By.CSS_SELECTOR, "div.text-xs, div.publication-volume")
            text = vol_div.text
            match = re.search(r'\b(19\d\d|20\d\d)\b', text)
            if match:
                date_str = match.group(1)
            else:
                date_str = text.strip()
        except Exception:
            pass

        if date_str == "N/A":
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date'], meta[name='citation_year']")
            date_str = meta_date.get_attribute("content")

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div#abss0001, div.abstract#abs0001, div.abstract")
            raw_text = abs_elem.text.strip()
        except Exception:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "#abs0001, div.AuthorAbstract")
            raw_text = abs_elem.text.strip()

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_tandfonline_data(driver):
    """
    Extracts structured paper details from Taylor & Francis Online (tandfonline.com).
    - Title: span.NLM_article-title, h1.article-title
    - Authors: div.hlFld-ContribAuthor div.entryAuthor a.author (e.g. Hamid Cheraghali, Peter Molnár)
    - Publication Date: span (containing "Published online:"), meta[name='citation_publication_date']
    - Abstract: div.hlFld-Abstract, div#abstractId1
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "span.NLM_article-title, h1.article-title, h1")
        # Strip badge text if present inside title span
        raw_title = driver.execute_script("""
            var elem = arguments[0].cloneNode(true);
            var badges = elem.querySelectorAll('.open_science_badges, .badge');
            badges.forEach(b => b.remove());
            return elem.innerText || elem.textContent;
        """, title_elem)
        data["title"] = raw_title.strip() if raw_title else title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elems = driver.find_elements(By.CSS_SELECTOR, "div.hlFld-ContribAuthor div.entryAuthor a.author, div.entryAuthor a.author")
        for elem in author_elems:
            raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", elem)
            clean_name = raw_name.strip() if raw_name else ""
            if clean_name and clean_name not in author_names:
                author_names.append(clean_name)

        if not author_names:
            links = driver.find_elements(By.CSS_SELECTOR, "a.author")
            for a in links:
                raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", a)
                clean_name = raw_name.strip() if raw_name else ""
                if clean_name and clean_name not in author_names:
                    author_names.append(clean_name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Date
    try:
        date_str = "N/A"
        try:
            spans = driver.find_elements(By.CSS_SELECTOR, "span")
            for s in spans:
                if "Published online:" in s.text:
                    date_str = s.text.replace("Published online:", "").strip()
                    break
        except Exception:
            pass

        if date_str == "N/A":
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date'], meta[name='dc.Date']")
            date_str = meta_date.get_attribute("content")

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div.hlFld-Abstract, div[id*='abstract'], div#abstractId1")
            raw_text = abs_elem.text.strip()
        except Exception:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div.abstract, section.abstract")
            raw_text = abs_elem.text.strip()

        if "ABSTRACT" in raw_text:
            raw_text = raw_text[raw_text.find("ABSTRACT"):]
        elif "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_degruyterbrill_data(driver):
    """
    Extracts structured paper details from De Gruyter Brill (degruyterbrill.com).
    - Title: h1.title-dgb, h1.title-dgb.no-ligatures, h1
    - Authors: li.contributors-AUTHOR span.contributor-dgb button.displayName (e.g. Yanxue Li, Hongjian Gao)
    - Publication Date: span.normal-product-text, meta[name='citation_publication_date']
    - Abstract: div.abstract, div.abstract p
    """
    data = {}
    
    # 1. Title
    try:
        title_text = driver.execute_script("""
            var h1 = document.querySelector("h1.title-dgb, h1[class*='title-dgb'], h1");
            if (h1 && h1.innerText && h1.innerText.trim() !== "" && h1.innerText.indexOf("Page not found") === -1) {
                return h1.innerText || h1.textContent;
            }
            var meta = document.querySelector("meta[name='citation_title'], meta[name='dc.Title']");
            return meta ? meta.getAttribute("content") : "";
        """)
        data["title"] = title_text.strip() if title_text else driver.title
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = driver.execute_script("""
            var names = [];
            var btns = document.querySelectorAll("li.contributors-AUTHOR span.contributor-dgb button.displayName, span.contributor-dgb button.displayName");
            btns.forEach(function(b) {
                var txt = (b.innerText || b.textContent).trim();
                if (txt && names.indexOf(txt) === -1) names.push(txt);
            });
            if (names.length === 0) {
                var popdowns = document.querySelectorAll("contributor-popdown");
                popdowns.forEach(function(p) {
                    var nameAttr = p.getAttribute("name");
                    if (nameAttr && names.indexOf(nameAttr.trim()) === -1) names.push(nameAttr.trim());
                });
            }
            return names;
        """)
        data["authors"] = author_names if author_names else []
    except Exception:
        data["authors"] = []

    # 3. Publication Date
    try:
        date_str = driver.execute_script("""
            var span = document.querySelector("span.normal-product-text, div.publicationDate span");
            if (span) return span.innerText || span.textContent;
            var meta = document.querySelector("meta[name='citation_publication_date'], meta[name='dc.Date']");
            return meta ? meta.getAttribute("content") : "N/A";
        """)
        data["published_date"] = date_str.strip() if date_str else "N/A"
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        abs_text = driver.execute_script("""
            var abs = document.querySelector("div.abstract, section.abstract, div[class*='abstract']");
            return abs ? (abs.innerText || abs.textContent) : "";
        """)
        raw_text = abs_text.strip() if abs_text else ""
        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_peerj_data(driver):
    """
    Extracts structured paper details from PeerJ (peerj.com).
    - Title: h1.article-title, h1[itemprop='name headline']
    - Authors: div.article-authors span.contrib span.name (e.g. Jianwei Tian, Hongyu Zhu)
    - Publication Date: span.article-meta-value, meta[name='citation_publication_date']
    - Abstract: div#article-item-abstract div.abstract (Strips self-citation footer)
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.article-title, h1[itemprop='name headline'], h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elems = driver.find_elements(By.CSS_SELECTOR, "div.article-authors span.contrib span.name, div.article-authors span.contrib a")
        for elem in author_elems:
            # Extract plain text of author name (given-names + surname)
            raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", elem)
            clean_name = re.sub(r'[\u200b\u200c\u200d\uFEFF]', '', raw_name).strip() if raw_name else ""
            clean_name = re.sub(r'[^\w\s\.\-]', '', clean_name).strip()
            if clean_name and clean_name not in author_names:
                author_names.append(clean_name)

        if not author_names:
            elems = driver.find_elements(By.CSS_SELECTOR, "div.article-authors span.contrib")
            for elem in elems:
                raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", elem)
                clean_name = raw_name.splitlines()[0].strip() if raw_name else ""
                if clean_name and clean_name not in author_names:
                    author_names.append(clean_name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Date
    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(By.CSS_SELECTOR, "span.article-meta-value, time[itemprop='datePublished']")
            date_str = date_elem.text.strip()
        except Exception:
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date'], meta[name='DC.date']")
            date_str = meta_date.get_attribute("content")

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div#article-item-abstract div.abstract, div.abstract")
            # Clone and remove self-citation footer from abstract container if present
            raw_text = driver.execute_script("""
                var clone = arguments[0].cloneNode(true);
                var selfCite = clone.querySelector('.self-citation, .alert');
                if (selfCite) selfCite.remove();
                return clone.innerText || clone.textContent;
            """, abs_elem)
        except Exception:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "#article-item-abstract-container, section.abstract")
            raw_text = abs_elem.text.strip()

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_nature_data(driver):
    """
    Extracts structured paper details from Nature (nature.com).
    - Title: h1.c-article-title / h1[data-test='article-title']
    - Authors: ul.c-article-author-list a[data-test='author-name'] (Extracts clean author names without SVG icons/superscripts)
    - Publication Date: time[datetime] / span.c-article-identifiers__item time
    - Abstract: section[aria-labelledby='Abs1'] / #Abs1-section / #Abs1-content
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.c-article-title, h1[data-test='article-title'], h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elems = driver.find_elements(By.CSS_SELECTOR, "ul.c-article-author-list a[data-test='author-name'], a[data-test='author-name']")
        for elem in author_elems:
            # Execute JS to get first child text node or innerText stripped of child elements
            raw_name = driver.execute_script(
                "return arguments[0].childNodes[0] ? arguments[0].childNodes[0].nodeValue : arguments[0].innerText;", elem
            )
            if not raw_name or not raw_name.strip():
                raw_name = elem.get_attribute("data-track-label") or elem.text
            clean_name = raw_name.strip() if raw_name else ""
            if clean_name and clean_name not in author_names:
                author_names.append(clean_name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Date
    try:
        date_str = "N/A"
        try:
            time_elem = driver.find_element(By.CSS_SELECTOR, "time[datetime], a[data-track-action='publication date'] time")
            date_str = time_elem.text.strip() or time_elem.get_attribute("datetime")
        except Exception:
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date'], meta[name='prism.publicationDate']")
            date_str = meta_date.get_attribute("content")

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "section[aria-labelledby='Abs1'], #Abs1-section, #Abs1-content, div.c-article-section#Abs1-section")
            raw_text = abs_elem.text.strip()
        except Exception:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div[id*='Abs'], section[class*='abstract']")
            raw_text = abs_elem.text.strip()

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

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
    - Title: h1.title / h1[itemprop='name']
    - Authors: div.art-authors -> div.profile-card-drop
    - Publication Date: span (starts with "Published:") or meta citation_publication_date
    - Abstract: div.html-p / section.html-abstract / #html-abstract
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.title, h1[itemprop='name'], h1")
        data["title"] = clean_title_text(title_elem.text.strip())
    except Exception:
        data["title"] = clean_title_text(driver.title)

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

    # 4. Abstract (Targets div.html-p directly or section.html-abstract)
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div.html-p, section.html-abstract div.html-p, div.art-abstract div.html-p")
            raw_text = abs_elem.text.strip()
        except Exception:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "section.html-abstract, #html-abstract, section.art-abstract, div.art-abstract, div.abstract_div")
            raw_text = abs_elem.text.strip()
        
        # Ensure abstract begins with 'Abstract' and excludes any preceding header block
        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_wiley_data(driver):
    """
    Extracts structured paper details from Wiley Online Library (onlinelibrary.wiley.com).
    - Title: h1.citation__title
    - Authors: div.accordion-tabbed -> span.accordion-tabbed__tab-mobile -> a.author-name -> span (Cleaned to extract just the author name)
    - Publication Date: span.epub-date
    - Abstract: section.article-section__abstract / section.article-section__abstract div.article-section__content
    """
    data = {}
    
    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.citation__title, h1.article-title, h1")
        data["title"] = title_elem.text.strip()
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elems = driver.find_elements(By.CSS_SELECTOR, "div.accordion-tabbed span.accordion-tabbed__tab-mobile a.author-name span, div.accordion-tabbed a.author-name span")
        for elem in author_elems:
            # Extract plain text of span (which excludes nested HTML if any or handles icons safely)
            raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", elem)
            clean_name = raw_name.strip() if raw_name else ""
            if clean_name and clean_name not in author_names:
                author_names.append(clean_name)

        if not author_names:
            links = driver.find_elements(By.CSS_SELECTOR, "a.author-name")
            for a in links:
                raw_name = driver.execute_script("return arguments[0].innerText || arguments[0].textContent;", a)
                clean_name = raw_name.splitlines()[0].strip() if raw_name else ""
                if clean_name and clean_name not in author_names:
                    author_names.append(clean_name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Date
    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(By.CSS_SELECTOR, "span.epub-date, span.primary-date")
            date_str = date_elem.text.strip()
        except Exception:
            meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_publication_date'], meta[name='citation_online_date']")
            date_str = meta_date.get_attribute("content")

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "section.article-section__abstract div.article-section__content, section.article-section__abstract")
            raw_text = abs_elem.text.strip()
        except Exception:
            abs_elem = driver.find_element(By.CSS_SELECTOR, "div.abstract-group, section[class*='abstract']")
            raw_text = abs_elem.text.strip()

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_ieeexplore_data(driver):
    """
    Extracts structured paper details from IEEE Xplore (ieeexplore.ieee.org).
    - Title: h1.document-title span, span[class*='document-title'], h1.document-title
    - Authors: div.authors-info-container span.authors-info a span, span.authors-info a span
    - Publication Year / Date: div.doc-abstract-confdate, div.doc-abstract-pubdate, or regex year
    - Abstract: span.abstract-text-content, div.abstract-text
    """
    data = {}

    # 1. Title
    try:
        title_elem = driver.find_element(
            By.CSS_SELECTOR,
            "h1.document-title span, h1.document-title, h1[class*='document-title'], h1"
        )
        data["title"] = clean_title_text(title_elem.text.strip())
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        # Target: div.authors-info-container span.authors-info a span
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.authors-info-container span.authors-info span.blue-tooltip a span, "
            "div.authors-info-container span.authors-info a span, "
            "div.authors-info-container span.authors-info a, "
            "span.authors-info-container a span"
        )
        for elem in author_elements:
            name = elem.text.strip()
            if name and name not in author_names and len(name) > 1:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        # Check metadata tags first (most reliable on IEEE)
        try:
            meta_date = driver.find_element(
                By.CSS_SELECTOR,
                "meta[name='citation_publication_date'], meta[name='citation_date'], meta[name='citation_online_date'], meta[name='citation_conference_date']"
            )
            val = meta_date.get_attribute("content")
            if val:
                date_str = val.strip()
        except Exception:
            pass

        # Look in visible DOM segments for published year
        if date_str == "N/A":
            date_selectors = [
                "div.doc-abstract-confdate",
                "div.doc-abstract-pubdate",
                "div[class*='publisher-info-container']",
                "div.u-pb-1"
            ]
            for sel in date_selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elements:
                    text = elem.text
                    match = re.search(r'\b(19\d\d|20\d\d)\b', text)
                    if match:
                        date_str = match.group(1)
                        break
                if date_str != "N/A":
                    break

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(
                By.CSS_SELECTOR,
                "span.abstract-text-content, div.abstract-text div, div.abstract-desktop-container, div.abstract-text"
            )
            raw_text = abs_elem.text.strip()
        except Exception:
            pass

        if not raw_text:
            try:
                meta_abs = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_abstract'], meta[property='og:description']")
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_plos_data(driver):
    """
    Extracts structured paper details from PLOS journals (journals.plos.org).
    - Title: h1#artTitle
    - Authors: ul#author-list li a.author-name
    - Publication Year / Date: li#artPubDate, meta citation_date
    - Abstract: div.abstract div.abstract-content, div.abstract
    """
    data = {}

    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1#artTitle, h1[class*='artTitle'], h1")
        raw_title = title_elem.text.strip()
        # Clean any XML processing instructions like <!--?xml ...--> or tags
        raw_title = re.sub(r'<\?[^>]*\?>', '', raw_title).strip()
        data["title"] = clean_title_text(raw_title)
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "ul#author-list li a.author-name, ul.author-list li a.author-name"
        )
        for elem in author_elements:
            name = elem.text.strip().rstrip(',').strip()
            if name and name not in author_names:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        try:
            pub_elem = driver.find_element(By.CSS_SELECTOR, "li#artPubDate, li[id*='artPubDate']")
            text = pub_elem.text.strip()
            # E.g. 'Published: October 7, 2025' -> extract 'October 7, 2025' or '2025'
            clean_date = re.sub(r'^(?:Published:\s*)', '', text, flags=re.IGNORECASE).strip()
            match = re.search(r'\b(19\d\d|20\d\d)\b', clean_date)
            date_str = match.group(1) if match else clean_date
        except Exception:
            pass

        if date_str == "N/A":
            try:
                meta_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_date'], meta[name='citation_publication_date']")
                date_str = meta_date.get_attribute("content")
            except Exception:
                pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(
                By.CSS_SELECTOR,
                "div.abstract-content, div.abstract, div[class*='abstract-content']"
            )
            raw_text = abs_elem.text.strip()
        except Exception:
            pass

        if not raw_text:
            try:
                meta_abs = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_abstract'], meta[property='og:description']")
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    return data

def extract_bentham_data(driver, item=None):
    """
    Extracts structured paper details from Bentham Science / Bentham Direct (benthamdirect.com).
    - Title: h1.h2, h1[class*='h2'], h1
    - Authors: div.authors, span.authors, meta citation_author
    - Publication Year / Date: div.pub-date, span.pub-date, meta citation_publication_date
    - Abstract: div.abstract p, p (containing Purpose/Methods/Results/Conclusion)
    """
    data = {}

    # 1. Title
    try:
        title_elem = driver.find_element(By.CSS_SELECTOR, "h1.h2, h1[class*='h2'], h1")
        data["title"] = clean_title_text(title_elem.text.strip())
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.authors a, span.author-name, a[class*='author'], div.author-list span, div.authors"
        )
        for elem in author_elements:
            name = elem.text.strip()
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author'], meta[name='dc.contributor']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        try:
            meta_date = driver.find_element(
                By.CSS_SELECTOR,
                "meta[name='citation_publication_date'], meta[name='citation_date'], meta[name='dc.date']"
            )
            val = meta_date.get_attribute("content")
            if val:
                match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                date_str = match.group(1) if match else val.strip()
        except Exception:
            pass

        if date_str == "N/A":
            date_elems = driver.find_elements(By.CSS_SELECTOR, "div.pub-date, span.pub-date, div[class*='date'], div[class*='publish']")
            for elem in date_elems:
                text = elem.text
                match = re.search(r'\b(19\d\d|20\d\d)\b', text)
                if match:
                    date_str = match.group(1)
                    break

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            # Look for paragraph or div containing abstract content
            abs_elems = driver.find_elements(By.CSS_SELECTOR, "div.abstract p, div[class*='abstract'] p, div.abstract, section[class*='abstract']")
            for elem in abs_elems:
                txt = elem.text.strip()
                if any(k in txt for k in ["Purpose:", "Methods:", "Results:", "Conclusion:", "Abstract"]):
                    raw_text = txt
                    break
            if not raw_text and abs_elems:
                raw_text = abs_elems[0].text.strip()
        except Exception:
            pass

        if not raw_text:
            try:
                meta_abs = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']")
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked by Cloudflare or fields are empty
    if not data.get("authors") or data.get("title") in ["www.benthamdirect.com", "Just a moment...", ""] or data.get("published_date") == "N/A":
        try:
            current_url = driver.current_url or ""
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', current_url)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    # Title fallback
                    if data.get("title") in ["www.benthamdirect.com", "Just a moment...", ""] and msg.get("title"):
                        data["title"] = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                    # Authors fallback
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    # Date fallback
                    if data.get("published_date") == "N/A":
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    # Abstract fallback
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    return data

def extract_sage_data(driver, item=None):
    """
    Extracts structured paper details from SAGE Journals (journals.sagepub.com / sagepub.com).
    - Title: h1[property='name'], h1.article-header__title, h1
    - Authors: div.contributors span[property='author'], span[property='author'], meta citation_author
    - Publication Year / Date: div.meta-panel__onlineDate, div[class*='onlineDate'], meta citation_publication_date
    - Abstract: div.abstractSection, div[class*='abstractSection'], div.abstract, section[class*='abstract']
    """
    data = {}

    # 1. Title
    try:
        title_elem = driver.find_element(
            By.CSS_SELECTOR,
            "h1[property='name'], h1.article-header__title, h1.citation__title, h1"
        )
        data["title"] = clean_title_text(title_elem.text.strip())
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        # Target: div.contributors span[property='author'] or span[property='author']
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.contributors span[property='author'], span[property='author'], div.contributors a[href*='#con']"
        )
        for elem in author_elements:
            try:
                # First try givenName + familyName
                given = elem.find_elements(By.CSS_SELECTOR, "span[property='givenName']")
                family = elem.find_elements(By.CSS_SELECTOR, "span[property='familyName']")
                if given and family:
                    name = f"{given[0].text.strip()} {family[0].text.strip()}".strip()
                else:
                    # Strip out email / orcid text if plain text
                    raw = elem.text.strip()
                    name = re.sub(r'https?://\S+|[\w\.-]+@[\w\.-]+', '', raw).strip().rstrip(',').strip()
                if name and name not in author_names and len(name) > 2:
                    author_names.append(name)
            except Exception:
                pass

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author'], meta[name='dc.Contributor']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(
                By.CSS_SELECTOR,
                "div.meta-panel__onlineDate, div[class*='onlineDate'], span.publicationContent__date"
            )
            text = date_elem.text.strip()
            # E.g. 'First published online December 13, 2024' -> regex match 4 digit year
            clean_date = re.sub(r'^(?:First published online\s*|Published\s*)', '', text, flags=re.IGNORECASE).strip()
            match = re.search(r'\b(19\d\d|20\d\d)\b', clean_date)
            date_str = match.group(1) if match else clean_date
        except Exception:
            pass

        if date_str == "N/A":
            try:
                meta_date = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_publication_date'], meta[name='citation_online_date'], meta[name='dc.Date']"
                )
                val = meta_date.get_attribute("content")
                if val:
                    match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    date_str = match.group(1) if match else val.strip()
            except Exception:
                pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(
                By.CSS_SELECTOR,
                "div.abstractSection, div[class*='abstractSection'], div.abstract, section[class*='abstract']"
            )
            raw_text = abs_elem.text.strip()
        except Exception:
            pass

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked by Cloudflare or fields are empty
    if not data.get("authors") or data.get("title") in ["journals.sagepub.com", "Just a moment...", ""] or data.get("published_date") == "N/A":
        try:
            current_url = driver.current_url or ""
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', current_url)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    # Title fallback
                    if data.get("title") in ["journals.sagepub.com", "Just a moment...", ""] and msg.get("title"):
                        data["title"] = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                    # Authors fallback
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    # Date fallback
                    if data.get("published_date") == "N/A":
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    # Abstract fallback
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    return data

def extract_aipp_data(driver, item=None):
    """
    Extracts structured paper details from AIP Publishing / Silverchair (pubs.aip.org).
    - Title: h1.wi-article-title, h1.article-title-main, h1
    - Authors: div.al-author-name a.linked-name, div.wi-authors a.linked-name
    - Publication Year / Date: span.article-date, meta citation_publication_date
    - Abstract: section.abstract p, div.abstract p, p (containing abstract text)
    """
    data = {}

    # 1. Title
    try:
        title_elem = driver.find_element(
            By.CSS_SELECTOR,
            "h1.wi-article-title, h1.article-title-main, h1[class*='article-title'], h1"
        )
        raw_title = title_elem.text.strip()
        raw_title = re.sub(r'(?i)\bOpen Access\b', '', raw_title).strip()
        data["title"] = clean_title_text(raw_title)
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.al-author-name a.linked-name, div.wi-authors a.linked-name, a.js-linked-name, div.al-authors-list div.al-author-name a"
        )
        for elem in author_elements:
            name = elem.text.strip()
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(
                By.CSS_SELECTOR,
                "span.article-date, div.article-date, span[class*='article-date']"
            )
            text = date_elem.text.strip()
            match = re.search(r'\b(19\d\d|20\d\d)\b', text)
            date_str = match.group(1) if match else text
        except Exception:
            pass

        if date_str == "N/A":
            try:
                meta_date = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_publication_date'], meta[name='citation_date'], meta[name='citation_online_date']"
                )
                val = meta_date.get_attribute("content")
                if val:
                    match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    date_str = match.group(1) if match else val.strip()
            except Exception:
                pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        try:
            abs_elem = driver.find_element(
                By.CSS_SELECTOR,
                "section.abstract p, div.abstract p, section.abstract, div.abstract, div[class*='abstract'] p"
            )
            raw_text = abs_elem.text.strip()
        except Exception:
            pass

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked by Cloudflare or fields are empty
    title_bad = data.get("title", "").strip().lower() in ["pubs.aip.org", "just a moment...", "", "superconductivity"]
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A":
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')
            
            # If not in target_str, parse standard AIP /article/ format: e.g. /139/2/023903/3377287
            # AIP DOIs are generally 10.1063/5.XXXXXXX
            if not doi:
                for candidate_url in [item_link, cur_url]:
                    art_match = re.search(r'/article/(?:doi/)?(10\.\d{4,9}/[^/?#]+)', candidate_url)
                    if art_match:
                        doi = art_match.group(1)
                        break

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            # Search Crossref by article ID if URL contains e.g. 3377287
            if not doi:
                for candidate_url in [item_link, cur_url]:
                    id_match = re.search(r'/article/\d+/\d+/(\d+)/(\d+)', candidate_url)
                    if id_match:
                        try:
                            import requests
                            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                            cr_s = requests.get(f"https://api.crossref.org/works?query.bibliographic={id_match.group(1)}+{id_match.group(2)}&rows=1", headers=headers, timeout=8)
                            if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                                doi = cr_s.json()["message"]["items"][0].get("DOI")
                        except Exception:
                            pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    if data.get("title", "").strip().lower() in ["pubs.aip.org", "just a moment...", ""]:
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_cambridge_data(driver, item=None):
    """
    Extracts structured paper details from Cambridge Core (cambridge.org/core).
    - Title: h1.title, h1[class*='article-title'], h1, meta[name='citation_title']
    - Authors: meta[name='citation_author'], ul.author-list li, span.author-name
    - Publication Year / Date: meta[name='citation_publication_date'], meta[name='citation_online_date'], span.date
    - Abstract: div.abstract, section.abstract, div[class*='abstract'], meta[name='citation_abstract']
    - Fallback: Crossref DOI / Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in ["h1.title", "h1[class*='article-title']", "h1.c-article-title", "h1"]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            data["title"] = clean_title_text(title_elem.text.strip())
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
        for ma in meta_authors:
            c = ma.get_attribute("content")
            if c and c.strip() and c.strip() not in author_names:
                author_names.append(c.strip())

        if not author_names:
            author_elements = driver.find_elements(
                By.CSS_SELECTOR,
                "ul.author-list li a, span.author-name, a[class*='author-name'], div.author a"
            )
            for elem in author_elements:
                name = elem.text.strip()
                if name and name not in author_names and len(name) > 2 and "\n" not in name:
                    author_names.append(name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        for meta_sel in [
            "meta[name='citation_publication_date']",
            "meta[name='citation_online_date']",
            "meta[name='citation_date']"
        ]:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                val = elem.get_attribute("content")
                if val:
                    match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    date_str = match.group(1) if match else val.strip()
                    break
            except Exception:
                pass

        if date_str == "N/A":
            try:
                date_elem = driver.find_element(
                    By.CSS_SELECTOR,
                    "span.date, div.published-date, span[class*='date']"
                )
                text = date_elem.text.strip()
                match = re.search(r'\b(19\d\d|20\d\d)\b', text)
                date_str = match.group(1) if match else text
            except Exception:
                pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div.abstract p", "section.abstract p", "div.abstract", "section.abstract",
            "div[class*='abstract'] p", "div[class*='abstract']", "div.content div.body"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                raw_text = "\n\n".join([e.text.strip() for e in elems if e.text.strip()])
                break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Fallback via Crossref if any core fields are missing or page is protected
    title_bad = data.get("title", "").strip().lower() in [
        "cambridge core", "just a moment...", "are you a robot", "attention required", ""
    ]
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    return data

def extract_rsc_data(driver, item=None):
    """
    Extracts structured paper details from Royal Society of Chemistry / Silverchair (pubs.rsc.org / rsc.org).
    - Title: h1.wi-article-title, h1.article-title-main, h1[class*='article-title'], h1
    - Authors: div.al-author-name a.linked-name, div.wi-authors a.linked-name, a.js-linked-name
    - Publication Year / Date: span.article-date, meta citation_publication_date
    - Abstract: p (within abstract container), section.abstract p, div.abstract p, div.capsule__column--p
    - Fallback: Crossref DOI / Title resolution for RSC publications
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1.wi-article-title", "h1.article-title-main",
            "h1[class*='article-title']", "h1[class*='wi-article-title']", "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            raw_title = title_elem.text.strip()
            raw_title = re.sub(r'(?i)\b(?:Open Access|Available to Purchase|Free Access)\b', '', raw_title).strip()
            data["title"] = clean_title_text(raw_title)
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.al-author-name a.linked-name, div.wi-authors a.linked-name, a.js-linked-name, div.al-authors-list div.al-author-name a"
        )
        for elem in author_elements:
            name = elem.text.strip()
            name = re.sub(r'[†*‡§\d]', '', name).strip()
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(
                By.CSS_SELECTOR,
                "span.article-date, div.article-date, span[class*='article-date']"
            )
            text = date_elem.text.strip()
            match = re.search(r'\b(19\d\d|20\d\d)\b', text)
            date_str = match.group(1) if match else text
        except Exception:
            pass

        if date_str == "N/A":
            for meta_sel in [
                "meta[name='citation_publication_date']",
                "meta[name='citation_online_date']",
                "meta[name='citation_date']"
            ]:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                    val = elem.get_attribute("content")
                    if val:
                        match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                        date_str = match.group(1) if match else val.strip()
                        break
                except Exception:
                    pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "section.abstract p", "div.abstract p", "section.abstract", "div.abstract",
            "div[class*='abstract'] p", "div[class*='abstract']", "div.capsule__column--p p", "div.capsule__column--p"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                raw_text = "\n\n".join([e.text.strip() for e in elems if e.text.strip()])
                break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked or missing fields
    title_bad = data.get("title", "").strip().lower() in [
        "pubs.rsc.org", "rsc publishing", "royal society of chemistry", "just a moment...", "are you a robot", ""
    ]
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    if data.get("title", "").strip().lower() in ["pubs.rsc.org", "rsc publishing", "royal society of chemistry", "just a moment...", ""]:
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_oaepublish_data(driver, item=None):
    """
    Extracts structured paper details from OAE Publishing (oaepublish.com).
    - Title: span.title_jmi, span[class*='title_'], h1.title, h1
    - Authors: div#authorString span.author_name, span.authors_item span.author_name
    - Publication Year / Date: span containing date (e.g. '21 Jun 2022'), meta citation_publication_date
    - Abstract: div.abstract_content p, div[class*='abstract'] p, p, meta[name='citation_abstract']
    - Fallback: Crossref DOI / Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "span.title_jmi", "span[class*='title_']", "h1.article-title",
            "h1.title", "div.article_title", "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            data["title"] = clean_title_text(title_elem.text.strip())
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div#authorString span.author_name, span.authors_item span.author_name, span.author_name, div#authorString h3"
        )
        for elem in author_elements:
            name = elem.text.strip()
            # Clean superscript numbers/commas/stars e.g. "Tian Lu1" -> "Tian Lu", "Minjie Li2,3,*" -> "Minjie Li"
            name = re.sub(r'[\d,*†‡§]', '', name).strip()
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        # Search page text for dates like "21 Jun 2022" or "2022"
        date_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "span[data-v-fbd9b55a], span.date, div.article_date, div.info-box span"
        )
        for elem in date_elements:
            txt = elem.text.strip()
            match = re.search(r'\b(?:(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})|(19\d\d|20\d\d))\b', txt, re.I)
            if match:
                date_str = match.group(0)
                year_match = re.search(r'\b(19\d\d|20\d\d)\b', date_str)
                if year_match:
                    date_str = year_match.group(1)
                break

        if date_str == "N/A":
            for meta_sel in [
                "meta[name='citation_publication_date']",
                "meta[name='citation_online_date']",
                "meta[name='citation_date']"
            ]:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                    val = elem.get_attribute("content")
                    if val:
                        match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                        date_str = match.group(1) if match else val.strip()
                        break
                except Exception:
                    pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div.abstract_content p", "div.article-abstract p", "div[class*='abstract'] p",
            "section.abstract p", "div.abstract_content", "div[class*='abstract']"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                raw_text = "\n\n".join([e.text.strip() for e in elems if e.text.strip()])
                break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked or missing fields
    title_bad = data.get("title", "").strip().lower() in [
        "oaepublish.com", "oae publishing", "journal of materials informatics", "just a moment...", "are you a robot", ""
    ]
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    if data.get("title", "").strip().lower() in ["oaepublish.com", "oae publishing", "journal of materials informatics", "just a moment...", ""]:
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_emerald_data(driver, item=None):
    """
    Extracts structured paper details from Emerald Insight / Silverchair (emerald.com/insight).
    - Title: h1.wi-article-title, h1.article-title-main, h1[class*='article-title'], h1
    - Authors: div.al-authors-list div.al-author-name a, div.wi-authors a.linked-name
    - Publication Year / Date: span.article-date, meta citation_publication_date
    - Abstract: p (in abstract container), section.abstract p, div.abstract p, meta[name='citation_abstract']
    - Fallback: Crossref DOI / Title resolution for Emerald publications
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1.wi-article-title", "h1.article-title-main",
            "h1[class*='article-title']", "h1[class*='wi-article-title']", "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            raw_title = title_elem.text.strip()
            raw_title = re.sub(r'(?i)\b(?:Open Access|Available to Purchase|Free Access)\b', '', raw_title).strip()
            data["title"] = clean_title_text(raw_title)
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.al-author-name a.linked-name, div.wi-authors a.linked-name, a.js-linked-name, div.al-authors-list div.al-author-name a"
        )
        for elem in author_elements:
            name = elem.text.strip()
            name = re.sub(r'[†*‡§\d]', '', name).strip()
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        try:
            date_elem = driver.find_element(
                By.CSS_SELECTOR,
                "span.article-date, div.article-date, span[class*='article-date']"
            )
            text = date_elem.text.strip()
            match = re.search(r'\b(19\d\d|20\d\d)\b', text)
            date_str = match.group(1) if match else text
        except Exception:
            pass

        if date_str == "N/A":
            for meta_sel in [
                "meta[name='citation_publication_date']",
                "meta[name='citation_online_date']",
                "meta[name='citation_date']"
            ]:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                    val = elem.get_attribute("content")
                    if val:
                        match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                        date_str = match.group(1) if match else val.strip()
                        break
                except Exception:
                    pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "section.abstract p", "div.abstract p", "section.abstract", "div.abstract",
            "div[class*='abstract'] p", "div[class*='abstract']", "section.abstract-section p"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                raw_text = "\n\n".join([e.text.strip() for e in elems if e.text.strip()])
                break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked or missing fields
    title_bad = data.get("title", "").strip().lower() in [
        "emerald.com", "emerald insight", "just a moment...", "are you a robot", "attention required", ""
    ]
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            art_match = re.search(r'/article/doi/(10\.\d{4,9}/[^/?#]+)(?:/\d+)?', target_str)
            if art_match:
                doi = art_match.group(1).rstrip('/')
            else:
                doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
                if doi_match:
                    doi = doi_match.group(0).rstrip('/')
                    if re.search(r'/\d{5,}$', doi):
                        doi = re.sub(r'/\d{5,}$', '', doi)

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    if data.get("title", "").strip().lower() in ["emerald.com", "emerald insight", "just a moment...", ""]:
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_asce_data(driver, item=None):
    """
    Extracts structured paper details from ASCE Library (ascelibrary.org).
    - Title: h1[property='name'], h1.citation__title, h1.article__title, h1
    - Authors: div.contributors span[property='author'], span[property='author'], a[href*='#con']
    - Publication Year / Date: div.meta-panel__onlineDate, span.epub-section__date, meta citation_publication_date
    - Abstract: div[role='paragraph'], div.abstractSection, div[class*='abstract'], meta[name='citation_abstract']
    - Fallback: Crossref DOI / Title resolution for ASCE publications
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1[property='name']", "h1.citation__title", "h1.article__title",
            "h1[class*='citation__title']", "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            data["title"] = clean_title_text(title_elem.text.strip())
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.contributors span[property='author'], span[property='author'], div.authors-wrapper span.author-name, div.contributors a[href*='#con']"
        )
        for elem in author_elements:
            # Check givenName + familyName inside element
            givens = elem.find_elements(By.CSS_SELECTOR, "span[property='givenName']")
            families = elem.find_elements(By.CSS_SELECTOR, "span[property='familyName']")
            if givens and families:
                g = givens[0].text.strip()
                f = families[0].text.strip()
                name = f"{g} {f}".strip()
            else:
                name = elem.text.strip()
                # strip out orcid URLs or email if captured
                name = re.sub(r'https?://[^\s]+', '', name)
                name = re.sub(r'[\w\.-]+@[\w\.-]+', '', name)
                name = re.sub(r'[†*‡§\d]', '', name).strip()
            
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date
    try:
        date_str = "N/A"
        date_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div.meta-panel__onlineDate, span.epub-section__date, div.meta-panel__date, span[class*='onlineDate']"
        )
        for elem in date_elements:
            txt = elem.text.strip()
            match = re.search(r'\b(19\d\d|20\d\d)\b', txt)
            if match:
                date_str = match.group(1)
                break

        if date_str == "N/A":
            for meta_sel in [
                "meta[name='citation_publication_date']",
                "meta[name='citation_online_date']",
                "meta[name='citation_date']"
            ]:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                    val = elem.get_attribute("content")
                    if val:
                        match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                        date_str = match.group(1) if match else val.strip()
                        break
                except Exception:
                    pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div[role='paragraph']", "div.abstractSection p", "div.abstractSection",
            "section.abstract p", "div.abstract p", "div[class*='abstract'] p", "div[class*='abstract']"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                raw_text = "\n\n".join([e.text.strip() for e in elems if e.text.strip()])
                break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked or missing fields
    title_bad = data.get("title", "").strip().lower() in [
        "asce library", "ascelibrary.org", "authorea", "authorea.com", "just a moment...", "are you a robot", "attention required", ""
    ]
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            art_match = re.search(r'/doi/(?:abs/|full/)?(10\.\d{4,9}/[^/?#]+)', target_str)
            if art_match:
                doi = art_match.group(1).rstrip('/')
            else:
                doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
                if doi_match:
                    doi = doi_match.group(0).rstrip('/')

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts") or msg.get("issued", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)

                    # 6. OpenAlex Abstract Fallback if Crossref does not have abstract
                    current_abs = data.get("abstract", "").strip()
                    if current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15:
                        try:
                            oa_resp = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}", headers=headers, timeout=8)
                            if oa_resp.status_code == 200:
                                inv = oa_resp.json().get("abstract_inverted_index")
                                if inv:
                                    words = sorted([(idx, word) for word, indices in inv.items() for idx in indices])
                                    oa_text = " ".join([w[1] for w in words]).strip()
                                    if oa_text:
                                        data["abstract"] = format_abstract_text(f"Abstract\n\n{oa_text}")
                        except Exception:
                            pass
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    if data.get("title", "").strip().lower() in ["asce library", "ascelibrary.org", "authorea", "authorea.com", "just a moment...", ""]:
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_medrxiv_data(driver, item=None):
    """
    Extracts structured paper details from medRxiv / bioRxiv / HighWire (medrxiv.org, biorxiv.org).
    - Title: h1.highwire-cite-title, h1#page-title, h1
    - Authors: span.highwire-citation-authors span.highwire-citation-author
    - Publication Year / Date: Extracted from DOI e.g. 10.1101/2026.02.09..., span.highwire-cite-metadata-doi, meta citation_date
    - Abstract: div.section.abstract, div#abstract-1, div[class*='abstract']
    - Fallback: Crossref / OpenAlex DOI & Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1.highwire-cite-title", "h1#page-title", "h1[class*='highwire-cite-title']", "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            data["title"] = clean_title_text(title_elem.text.strip())
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "span.highwire-citation-authors span.highwire-citation-author, span.highwire-citation-author"
        )
        for elem in author_elements:
            givens = elem.find_elements(By.CSS_SELECTOR, "span.nlm-given-names")
            surnames = elem.find_elements(By.CSS_SELECTOR, "span.nlm-surname")
            if givens and surnames:
                g = givens[0].text.strip()
                s = surnames[0].text.strip()
                name = f"{g} {s}".strip()
            else:
                name = elem.text.strip()
                name = re.sub(r'View ORCID Profile', '', name).strip()
                name = re.sub(r'https?://[^\s]+', '', name).strip()
                name = re.sub(r'[\d,*†‡§]', '', name).strip()

            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author']")
            for ma in meta_authors:
                content = ma.get_attribute("content")
                if content and content.strip() not in author_names:
                    author_names.append(content.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year / Date (from medRxiv / bioRxiv DOI or page date)
    try:
        date_str = "N/A"
        # Strategy A: Extract date from highwire DOI string or URL (e.g. 10.1101/2026.02.09.26345941 -> 2026)
        doi_text = ""
        doi_elems = driver.find_elements(By.CSS_SELECTOR, "span.highwire-cite-metadata-doi, span[class*='metadata-doi']")
        if doi_elems:
            doi_text = doi_elems[0].text.strip()

        combined_doi_source = f"{doi_text} {driver.current_url or ''}"
        if item and isinstance(item, dict):
            combined_doi_source += f" {item.get('link', '')} {item.get('document_link', '')}"

        # Look for YYYY.MM.DD in the DOI or URL
        doi_date_match = re.search(r'\b(19\d\d|20\d\d)\.\d{2}\.\d{2}\b', combined_doi_source)
        if doi_date_match:
            date_str = doi_date_match.group(1)

        # Strategy B: Search page date elements or meta tags
        if date_str == "N/A":
            for meta_sel in [
                "meta[name='citation_date']",
                "meta[name='citation_publication_date']",
                "meta[name='citation_online_date']",
                "meta[name='DC.Date']"
            ]:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                    val = elem.get_attribute("content")
                    if val:
                        match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                        if match:
                            date_str = match.group(1)
                            break
                except Exception:
                    pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div.section.abstract", "div#abstract-1", "div.abstract",
            "section.abstract", "div[class*='abstract']"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                # If subsection paragraphs exist, join them
                p_elems = elems[0].find_elements(By.CSS_SELECTOR, "div.subsection p, p")
                if p_elems and any(p.text.strip() for p in p_elems):
                    raw_text = "\n\n".join([p.text.strip() for p in p_elems if p.text.strip()])
                else:
                    raw_text = elems[0].text.strip()
                break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked or missing fields
    cur_title = data.get("title", "").strip().lower()
    title_bad = cur_title in [
        "medrxiv", "biorxiv", "www.medrxiv.org", "www.biorxiv.org",
        "just a moment...", "are you a robot", "attention required", ""
    ] or "medrxiv" == cur_title or cur_title.startswith("www.")
    
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')
                # Remove URL suffixes like .abstract or .full
                doi = re.sub(r'\.(?:abstract|full|pdf|article)$', '', doi, flags=re.I)

            # Search Crossref by paper title if available
            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("issued", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    cur_title_final = data.get("title", "").strip().lower()
    if cur_title_final in ["medrxiv", "biorxiv", "www.medrxiv.org", "www.biorxiv.org", "just a moment...", ""] or cur_title_final.startswith("www."):
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_dergipark_data(driver, item=None):
    """
    Extracts structured paper details from DergiPark (dergipark.org.tr).
    - Title: h1[class*='font-extrabold'], h1.article-title, h1.drop-shadow-md, h1
    - Authors: a[href*='/pub/@'], a[title*='Author'], div.article-authors a, span.author
    - Publication Year: span or div with month year (e.g. 'June 1, 2026' -> 2026), meta citation_publication_date
    - Abstract: div.abstract-text, div.article-abstract, div[class*='abstract-text'], div.text-justify
    - Fallback: Crossref / OpenAlex DOI & Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1[class*='font-extrabold']", "h1.article-title", "h1[class*='drop-shadow']",
            "h1.font-heading", "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            data["title"] = clean_title_text(title_elem.text.strip())
        else:
            meta_t = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_title']")
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        author_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "a[href*='/pub/@'], a[title*='Author'], a[title*='author'], div.article-authors a, span.author"
        )
        for elem in author_elements:
            name = elem.text.strip()
            # strip out orcid URLs or email if captured
            name = re.sub(r'https?://[^\s]+', '', name)
            name = re.sub(r'[\w\.-]+@[\w\.-]+', '', name)
            name = re.sub(r'[†*‡§\d]', '', name).strip()
            if name and name not in author_names and len(name) > 2 and "\n" not in name:
                author_names.append(name)

        if not author_names:
            meta_authors = driver.find_elements(By.CSS_SELECTOR, "meta[name='citation_author'], meta[name='DC.Creator']")
            for ma in meta_authors:
                val = ma.get_attribute("content")
                if val and val.strip() and val.strip() not in author_names:
                    author_names.append(val.strip())

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year
    try:
        date_str = "N/A"
        # Check meta tags first
        for meta_sel in [
            "meta[name='citation_date']",
            "meta[name='citation_publication_date']",
            "meta[name='citation_online_date']",
            "meta[name='DC.Date']"
        ]:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, meta_sel)
                val = elem.get_attribute("content")
                if val:
                    match = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    if match:
                        date_str = match.group(1)
                        break
            except Exception:
                pass

        # Strategy B: Find text containing 4-digit year like "June 1, 2026" or "2026"
        if date_str == "N/A":
            for sel in ["span", "div.article-subtitle", "div.kt-portlet__head-title", "div.article-info"]:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    for el in elems[:30]:
                        txt = el.text.strip()
                        if any(month in txt.lower() for month in ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]):
                            match = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                            if match:
                                date_str = match.group(1)
                                break
                    if date_str != "N/A":
                        break
                except Exception:
                    pass

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div.abstract-text",
            "div[class*='abstract-text']",
            "div.article-abstract",
            "div.article-body",
            "div.text-justify"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                # prefer the one containing keywords or sufficient length
                for el in elems:
                    t = el.text.strip()
                    if len(t) > 50:
                        raw_text = t
                        break
                if raw_text:
                    break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                raw_text = meta_abs.get_attribute("content") or ""
            except Exception:
                pass

        if "Abstract" in raw_text:
            raw_text = raw_text[raw_text.find("Abstract"):]
        else:
            raw_text = "Abstract\n\n" + raw_text

        data["abstract"] = format_abstract_text(raw_text)
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref Fallback if blocked or missing fields
    cur_title = data.get("title", "").strip().lower()
    title_bad = cur_title in [
        "dergipark", "dergipark.org.tr", "just a moment...", "are you a robot", "attention required", ""
    ] or "dergipark" in cur_title or cur_title.startswith("www.")
    
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            target_str = f"{doc_link} {item_link} {cur_url}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')
                doi = re.sub(r'\.(?:abstract|full|pdf|article)$', '', doi, flags=re.I)

            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                cr_resp = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=8)
                if cr_resp.status_code == 200:
                    msg = cr_resp.json().get("message", {})
                    if msg.get("title"):
                        clean_t = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
                        if title_bad or len(data.get("title", "")) < len(clean_t):
                            data["title"] = clean_title_text(clean_t)
                    if not data.get("authors") and msg.get("author"):
                        cr_authors = []
                        for a in msg["author"]:
                            g = a.get("given", "").strip()
                            f = a.get("family", "").strip()
                            name = f"{g} {f}".strip() if g and f else (f or g)
                            if name and name not in cr_authors:
                                cr_authors.append(name)
                        if cr_authors:
                            data["authors"] = cr_authors
                    if data.get("published_date") in ["N/A", "None", None]:
                        date_parts = msg.get("published-online", {}).get("date-parts") or msg.get("issued", {}).get("date-parts") or msg.get("published-print", {}).get("date-parts")
                        if date_parts and date_parts[0]:
                            data["published_date"] = str(date_parts[0][0])
                    current_abs = data.get("abstract", "").strip()
                    if (current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15) and msg.get("abstract"):
                        clean_abs = re.sub(r'<[^>]+>', '', msg["abstract"]).strip()
                        if "Abstract" in clean_abs:
                            clean_abs = clean_abs[clean_abs.find("Abstract"):]
                        else:
                            clean_abs = "Abstract\n\n" + clean_abs
                        data["abstract"] = format_abstract_text(clean_abs)

                    # OpenAlex fallback if Crossref does not have abstract
                    current_abs = data.get("abstract", "").strip()
                    if current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15:
                        try:
                            oa_resp = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}", headers=headers, timeout=8)
                            if oa_resp.status_code == 200:
                                inv = oa_resp.json().get("abstract_inverted_index")
                                if inv:
                                    words = sorted([(idx, word) for word, indices in inv.items() for idx in indices])
                                    oa_text = " ".join([w[1] for w in words]).strip()
                                    if oa_text:
                                        data["abstract"] = format_abstract_text(f"Abstract\n\n{oa_text}")
                        except Exception:
                            pass
        except Exception:
            pass

    # Safety fallback: if title is still the domain, use item title if provided
    cur_title_final = data.get("title", "").strip().lower()
    if cur_title_final in ["dergipark", "dergipark.org.tr", "just a moment...", ""] or cur_title_final.startswith("www."):
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

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
    - Uses Undetected Humanoid mode for cell.com and wiley.com (CAPTCHA protected).
    - Uses fast, lightweight driver for all other domains.
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
    current_driver_type = None

    try:
        for item in link_items:
            url = item["link"]
            parsed_domain = urlparse(url).netloc.lower()
            needs_captcha_humanoid = ("cell.com" in parsed_domain) or ("wiley.com" in parsed_domain) or ("sciencedirect.com" in parsed_domain) or ("tandfonline.com" in parsed_domain) or ("benthamdirect.com" in parsed_domain) or ("sagepub.com" in parsed_domain) or ("aip.org" in parsed_domain) or ("cambridge.org" in parsed_domain) or ("rsc.org" in parsed_domain) or ("emerald.com" in parsed_domain) or ("ascelibrary.org" in parsed_domain) or ("authorea.com" in parsed_domain) or ("medrxiv.org" in parsed_domain) or ("biorxiv.org" in parsed_domain)

            required_type = "captcha_humanoid" if needs_captcha_humanoid else "lite"
            if current_driver_type != required_type:
                if current_driver:
                    try:
                        current_driver.quit()
                    except Exception:
                        pass
                
                if required_type == "captcha_humanoid":
                    print("[*] 🛡️ Initializing Undetected Humanoid Browser (Cell / Wiley / ScienceDirect / TandF / Cambridge / RSC / Emerald / ASCE / medRxiv Mode)...")
                    current_driver = create_humanoid_driver(headless=headless)
                else:
                    print("[*] ⚡ Initializing Fast Lite Browser (Springer/Frontiers/MDPI/Nature Mode)...")
                    current_driver = create_lite_driver(headless=headless)
                
                current_driver_type = required_type

            print(f"------------------------------------------------------------------")
            print(f"[+] ITEM [{item['index'] + 1}/{total}]")
            print(f"[+] Target URL: {url}")
            print(f"------------------------------------------------------------------")
            
            try:
                start_time = time.time()
                current_driver.get(url)
                
                if needs_captcha_humanoid:
                    # Poll for target title/abstract elements after manual user resolution / Cloudflare auto-check
                    target_selectors = [
                        "h1.highwire-cite-title", "div.section.abstract", "div#abstract-1",
                        "h1.wi-article-title", "h1.article-title-main",
                        "h1.h2", "h1[class*='h2']",
                        "span.NLM_article-title", "div.hlFld-Abstract", "div#abstractId1",
                        "span.title-text", "h1.title-text", "div.author-group", "div#abs0001", "div#abss0001",
                        "h1.citation__title", "h1[property='name']", "h1.article-header__title", "h1.article-title",
                        "section.article-section__abstract", "section#author-abstract", "div.article-tools__abstract",
                        "div.abstract", "#abstract", "div.abstract-group", "section[class*='abstract']",
                        "h1.title", "h1[class*='article-title']"
                    ]
                    found = wait_for_captcha_and_content(current_driver, target_selectors, timeout=40)
                    if not found:
                        humanoid_mouse_and_scroll(current_driver)
                        wait_for_captcha_and_content(current_driver, target_selectors, timeout=10)
                else:
                    # For fast lite sites (Springer, MDPI, Frontiers, Nature, De Gruyter Brill), wait up to 6 seconds for title/body element
                    fast_selectors = [
                        "h1.highwire-cite-title", "span.highwire-citation-authors", "div.section.abstract",
                        "span.title_jmi", "div#authorString", "div.article-authors",
                        "h1#artTitle", "div.abstract-content",
                        "h1.title-dgb", "h1[class*='title-dgb']", "h1.c-article-title",
                        "h1[data-test='article-title']", "h1.title", "h1[itemprop='name']",
                        "h1.ArticleDetailsV4__main__title", "h1.document-title", "span.abstract-text-content",
                        "h1[class*='font-extrabold']", "div.abstract-text", "div[class*='abstract-text']", "h1"
                    ]
                    for _ in range(12):
                        try:
                            if any(current_driver.find_elements(By.CSS_SELECTOR, s) for s in fast_selectors):
                                break
                        except Exception:
                            pass
                        time.sleep(0.5)

                elapsed = time.time() - start_time
                print(f"[+] Loaded & Content Detected in {elapsed:.2f} seconds!")

                scraped_data = {}
                
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

                elif "wiley.com" in parsed_domain:
                    print(f"[*] Wiley Online Library Detected -> Extracting Wiley Article Elements...")
                    scraped_data = extract_wiley_data(current_driver)
                    
                    print(f"\n--- [ Wiley Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "nature.com" in parsed_domain:
                    print(f"[*] Nature Domain Detected -> Extracting Nature Article Elements...")
                    scraped_data = extract_nature_data(current_driver)
                    
                    print(f"\n--- [ Nature Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "peerj.com" in parsed_domain:
                    print(f"[*] PeerJ Domain Detected -> Extracting PeerJ Article Elements...")
                    scraped_data = extract_peerj_data(current_driver)
                    
                    print(f"\n--- [ PeerJ Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "sciencedirect.com" in parsed_domain:
                    print(f"[*] ScienceDirect Domain Detected -> Extracting ScienceDirect Article Elements...")
                    scraped_data = extract_sciencedirect_data(current_driver)
                    
                    print(f"\n--- [ ScienceDirect Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "tandfonline.com" in parsed_domain:
                    print(f"[*] Taylor & Francis Domain Detected -> Extracting TandF Online Article Elements...")
                    scraped_data = extract_tandfonline_data(current_driver)
                    
                    print(f"\n--- [ Taylor & Francis Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "degruyterbrill.com" in parsed_domain or "degruyter.com" in parsed_domain:
                    print(f"[*] De Gruyter Brill Domain Detected -> Extracting De Gruyter Article Elements...")
                    scraped_data = extract_degruyterbrill_data(current_driver)
                    
                    print(f"\n--- [ De Gruyter Brill Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "ieeexplore.ieee.org" in parsed_domain:
                    print(f"[*] IEEE Xplore Domain Detected -> Extracting IEEE Article Elements...")
                    scraped_data = extract_ieeexplore_data(current_driver)

                    print(f"\n--- [ IEEE Xplore Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "plos.org" in parsed_domain:
                    print(f"[*] PLOS Domain Detected -> Extracting PLOS Article Elements...")
                    scraped_data = extract_plos_data(current_driver)

                    print(f"\n--- [ PLOS Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "benthamdirect.com" in parsed_domain or "benthamscience.com" in parsed_domain:
                    print(f"[*] Bentham Science Domain Detected -> Extracting Bentham Article Elements...")
                    scraped_data = extract_bentham_data(current_driver, item=item)

                    print(f"\n--- [ Bentham Science Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "sagepub.com" in parsed_domain:
                    print(f"[*] SAGE Journals Domain Detected -> Extracting SAGE Article Elements...")
                    scraped_data = extract_sage_data(current_driver, item=item)

                    print(f"\n--- [ SAGE Journals Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "aip.org" in parsed_domain:
                    print(f"[*] AIP Publishing Domain Detected -> Extracting AIP Article Elements...")
                    scraped_data = extract_aipp_data(current_driver, item=item)

                    print(f"\n--- [ AIP Publishing Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "cambridge.org" in parsed_domain:
                    print(f"[*] Cambridge Core Domain Detected -> Extracting Cambridge Article Elements...")
                    scraped_data = extract_cambridge_data(current_driver, item=item)

                    print(f"\n--- [ Cambridge Core Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "rsc.org" in parsed_domain:
                    print(f"[*] Royal Society of Chemistry Domain Detected -> Extracting RSC Article Elements...")
                    scraped_data = extract_rsc_data(current_driver, item=item)

                    print(f"\n--- [ Royal Society of Chemistry Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "oaepublish.com" in parsed_domain:
                    print(f"[*] OAE Publishing Domain Detected -> Extracting OAE Article Elements...")
                    scraped_data = extract_oaepublish_data(current_driver, item=item)

                    print(f"\n--- [ OAE Publishing Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "emerald.com" in parsed_domain:
                    print(f"[*] Emerald Insight Domain Detected -> Extracting Emerald Article Elements...")
                    scraped_data = extract_emerald_data(current_driver, item=item)

                    print(f"\n--- [ Emerald Insight Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "ascelibrary.org" in parsed_domain or "authorea.com" in parsed_domain:
                    print(f"[*] ASCE Library / Authorea Domain Detected -> Extracting Article Elements...")
                    scraped_data = extract_asce_data(current_driver, item=item)

                    print(f"\n--- [ ASCE Library / Authorea Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "medrxiv.org" in parsed_domain or "biorxiv.org" in parsed_domain:
                    print(f"[*] medRxiv / bioRxiv Domain Detected -> Extracting Preprint Elements...")
                    scraped_data = extract_medrxiv_data(current_driver, item=item)

                    print(f"\n--- [ medRxiv / bioRxiv Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "dergipark.org.tr" in parsed_domain or "dergipark" in parsed_domain:
                    print(f"[*] DergiPark Domain Detected -> Extracting DergiPark Article Elements...")
                    scraped_data = extract_dergipark_data(current_driver, item=item)

                    print(f"\n--- [ DergiPark Extracted Data ] ---")
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
