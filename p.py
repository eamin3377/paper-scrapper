import sys
import os
import json
import csv
import time
import re
import random
import io
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import undetected_chromedriver as uc
    HAS_UC = True
    uc.Chrome.__del__ = lambda self: None
except ImportError:
    HAS_UC = False

try:
    from langdetect import detect_langs
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False

def is_text_english(title, abstract=None):
    """
    Checks whether a paper's title or abstract is in English.
    Returns False if foreign language (e.g. Spanish, Turkish, Portuguese, Chinese, Korean, Arabic, French, German).
    """
    # 1. Reject non-Latin scripts (Chinese, Japanese, Korean, Arabic, Cyrillic)
    full_str = f"{title or ''} {abstract or ''}"
    if re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0600-\u06ff\u0400-\u04ff]', full_str):
        return False

    # 2. Check abstract language if substantial
    if HAS_LANGDETECT:
        clean_abs = (abstract or "").replace("Abstract", "").strip()
        if clean_abs and len(clean_abs) > 50:
            try:
                langs = detect_langs(clean_abs[:400])
                top = langs[0]
                if top.lang != 'en' and top.prob > 0.85:
                    return False
            except Exception:
                pass

        if title and len(title.strip()) > 10:
            try:
                t_langs = detect_langs(title)
                top_t = t_langs[0]
                if top_t.lang in ['tr', 'pt', 'es', 'de', 'fr', 'sk', 'id'] and top_t.prob > 0.90:
                    lower_t = title.lower()
                    foreign_markers = ['ve', 'ile', 'veya', 'bir', 'için', 'uma', 'para', 'com', 'da', 'do', 'em', 'der', 'die', 'und', 'von', 'des', 'les', 'pour', 'dans', 'del', 'los', 'las', 'por', 'ako', 'pre']
                    if any(w in lower_t.split() for w in foreign_markers):
                        return False
            except Exception:
                pass

    return True

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

    # Launch Chrome in Incognito mode for clean, un-cached, fast loading
    options.add_argument("--incognito")
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
    Runs in Incognito mode to avoid cached bot telemetry and stale cookies.
    """
    chrome_major_version = get_installed_chrome_version()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

    if HAS_UC:
        options = uc.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        
        # Enable Chrome Incognito mode
        options.add_argument("--incognito")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=en-US,en")
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

def wait_for_captcha_and_content(driver, selectors, timeout=30):
    """
    Polls the DOM naturally. If Cloudflare Turnstile or security challenge is active,
    it stays completely quiet and idle, allowing the human to click the box without
    any synthetic actions interfering with the verification.
    As soon as verification clears and article content appears, returns True.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            title = driver.title.lower()
            # If still on Cloudflare challenge screen, do not touch or scroll
            if "are you a robot" in title or "just a moment" in title or "cloudflare" in title or "attention required" in title:
                time.sleep(1.0)
                continue

            for selector in selectors:
                elems = driver.find_elements(By.CSS_SELECTOR, selector)
                if elems and any(e.text.strip() for e in elems):
                    return True
        except Exception:
            pass
        time.sleep(0.8)
    return False

def humanoid_mouse_and_scroll(driver):
    """
    Gently scrolls only if we are already on an article page, never while on a verification challenge.
    """
    try:
        title = driver.title.lower()
        if "are you a robot" in title or "just a moment" in title or "cloudflare" in title or "attention required" in title:
            return

        total_height = int(driver.execute_script("return document.body.scrollHeight"))
        if total_height > 500:
            scroll_target = random.randint(200, min(600, total_height))
            driver.execute_script(f"window.scrollTo({{top: {scroll_target}, behavior: 'smooth'}});")
            time.sleep(random.uniform(0.6, 1.0))
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

    bot_phrases = [
        "security service to protect",
        "protect against malicious bots",
        "verifies you are not a bot",
        "enable javascript and cookies",
        "ray id:",
        "cloudflare"
    ]
    if any(bp in text.lower() for bp in bot_phrases):
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
    Extracts structured paper details from Royal Society of Chemistry / American Chemical Society / Silverchair (pubs.rsc.org, pubs.acs.org).
    - Title: h1.wi-article-title, h1.article-title-main, h1[class*='article-title'], h1
    - Authors: div.al-author-name a.linked-name, div.wi-authors a.linked-name, a.js-linked-name, div.al-authors-list div.al-author-name a
    - Publication Year / Date: span.article-date, meta citation_publication_date
    - Abstract: p.articleBody_abstractText, div.article_abstract p, section.abstract p, div.abstract p, p
    - Fallback: Crossref DOI / Title resolution for RSC/ACS publications
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
            # Clone and remove any badges, access icons, or purchase buttons
            raw_title = driver.execute_script("""
                var clone = arguments[0].cloneNode(true);
                var badges = clone.querySelectorAll('span[data-resource-id-access], .js-access-icon-placeholder, .screenreader-text, .badge');
                badges.forEach(b => b.remove());
                return clone.innerText || clone.textContent;
            """, title_elem)
            raw_title = raw_title.strip() if raw_title else title_elem.text.strip()
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
        author_blocks = driver.find_elements(By.CSS_SELECTOR, "div.al-authors-list div.al-author-name, div.wi-authors div.al-author-name")
        if author_blocks:
            for block in author_blocks:
                try:
                    # Extract the clean name from the author link or info-card-name
                    name_text = driver.execute_script("""
                        var clone = arguments[0].cloneNode(true);
                        // Remove modal panels, footnotes, screenreader, and icons
                        var junk = clone.querySelectorAll('.al-author-info-wrap, .info-card-footnote, .screenreader-text, i, span.xref-corresp, span.xref-author-notes, .al-orcid-info-wrap, .al-author-delim');
                        junk.forEach(j => j.remove());
                        var link = clone.querySelector('a.linked-name, a.js-linked-name, a');
                        if (link) {
                            return link.innerText || link.textContent;
                        }
                        return clone.innerText || clone.textContent;
                    """, block)
                    if name_text:
                        name = name_text.strip()
                        name = re.sub(r'[\r\n\t]+', ' ', name)
                        name = re.sub(r'[†*‡§\d]', '', name).strip()
                        name = re.sub(r'\s+', ' ', name).strip()
                        if name and name not in author_names and len(name) > 2 and not name.lower().startswith("close"):
                            author_names.append(name)
                except Exception:
                    pass

        if not author_names:
            author_elements = driver.find_elements(
                By.CSS_SELECTOR,
                "div.al-author-name a.linked-name, div.wi-authors a.linked-name, a.js-linked-name, div.al-authors-list div.al-author-name a"
            )
            for elem in author_elements:
                name = elem.text.strip()
                name = re.sub(r'[\r\n\t]+', ' ', name)
                name = re.sub(r'[†*‡§\d]', '', name).strip()
                if name and name not in author_names and len(name) > 2 and not name.lower().startswith("close"):
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
            "p.articleBody_abstractText", "div.article_abstract p", "div.article_abstract",
            "section.abstract p", "div.abstract p", "section.abstract", "div.abstract",
            "div[class*='abstract'] p", "div[class*='abstract']", "div.capsule__column--p p", "div.capsule__column--p",
            "div.hlFld-Abstract p", "div.hlFld-Abstract", "article p", "main p"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            # Find the element with substantial text (at least 60 characters)
            valid_texts = [e.text.strip() for e in elems if len(e.text.strip()) >= 60]
            if valid_texts:
                raw_text = "\n\n".join(valid_texts)
                break

        # Fallback to general paragraph scan if not found
        if not raw_text or len(raw_text) < 40:
            for p in driver.find_elements(By.TAG_NAME, "p"):
                t = p.text.strip()
                t_low = t.lower()
                if len(t) > 100 and not any(skip in t_low for skip in [
                    "cookie", "terms of use", "privacy policy", "rights reserved",
                    "security service to protect", "verifies you are not a bot", "malicious bots"
                ]):
                    raw_text = t
                    break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='citation_abstract'], meta[name='description'], meta[property='og:description']"
                )
                meta_content = meta_abs.get_attribute("content") or ""
                if len(meta_content.strip()) > 30 and "article published in" not in meta_content.lower() and "security service" not in meta_content.lower():
                    raw_text = meta_content
            except Exception:
                pass

        if raw_text:
            if "Abstract" in raw_text:
                raw_text = raw_text[raw_text.find("Abstract"):]
            else:
                raw_text = "Abstract\n\n" + raw_text
            data["abstract"] = format_abstract_text(raw_text)
        else:
            data["abstract"] = "N/A"
    except Exception:
        data["abstract"] = "N/A"

    # 5. Crossref / OpenAlex Fallback if blocked or missing fields
    title_bad = data.get("title", "").strip().lower() in [
        "pubs.rsc.org", "rsc publishing", "royal society of chemistry",
        "pubs.acs.org", "acs publications", "american chemical society",
        "just a moment...", "are you a robot", ""
    ]
    cur_abs = data.get("abstract", "").strip().lower()
    abs_bad = (
        cur_abs in ["n/a", "", "abstract"] or
        len(cur_abs) <= 25 or
        "security service to protect" in cur_abs or
        "verifies you are not a bot" in cur_abs or
        "malicious bots" in cur_abs
    )
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or abs_bad:
        try:
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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

                # Fallback to OpenAlex if abstract is still missing (common for ACS / paywalled preprints)
                current_abs = data.get("abstract", "").strip()
                if current_abs in ["N/A", "", "Abstract"] or len(current_abs) <= 15:
                    try:
                        oa_url = f"https://api.openalex.org/works/https://doi.org/{doi}"
                        oa_resp = requests.get(oa_url, headers=headers, timeout=8)
                        if oa_resp.status_code == 200:
                            oa_data = oa_resp.json()
                            inv = oa_data.get("abstract_inverted_index")
                            if inv:
                                words = sorted([(pos, w) for w, poses in inv.items() for pos in poses])
                                reconstructed_abs = " ".join(w for _, w in words).strip()
                                if reconstructed_abs:
                                    data["abstract"] = format_abstract_text("Abstract\n\n" + reconstructed_abs)
                    except Exception:
                        pass
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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

def extract_bepress_data(driver, item=None):
    """
    Extracts structured paper details from Digital Commons / Bepress repositories
    such as Karbala International Journal of Modern Science (kijoms.uokerbala.edu.iq).
    - Title: h1 a[href*='viewcontent.cgi'], h1, p#title, meta bepress_citation_title, meta citation_title
    - Authors: strong tags inside author sections / paragraphs, meta bepress_citation_author, meta author
    - Publication Year: a[href*='/vol'], meta bepress_citation_date, meta citation_date
    - Abstract: div#abstract p, div#abstract, div.abstract, meta description
    - Fallback: Crossref / OpenAlex DOI & Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1 a[href*='viewcontent.cgi']",
            "p#title a",
            "p#title",
            "div#title a",
            "div#title",
            "h1.article-title",
            "h1"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            if elems and any(e.text.strip() for e in elems):
                title_elem = [e for e in elems if e.text.strip()][0]
                break

        if title_elem:
            data["title"] = clean_title_text(title_elem.text.strip())
        else:
            meta_t = driver.find_element(
                By.CSS_SELECTOR,
                "meta[name='bepress_citation_title'], meta[name='citation_title'], meta[property='og:title']"
            )
            data["title"] = clean_title_text(meta_t.get_attribute("content") or "")
    except Exception:
        data["title"] = driver.title

    # 2. Authors
    try:
        author_names = []
        # Find strong tags (e.g. <strong>Ricardo Huamantingo</strong>)
        strong_elems = driver.find_elements(By.CSS_SELECTOR, "p.author strong, div#authors strong, div.author-info strong, strong")
        for elem in strong_elems:
            name = elem.text.strip()
            name = re.sub(r'https?://[^\s]+', '', name)
            name = re.sub(r'[\w\.-]+@[\w\.-]+', '', name)
            name = re.sub(r'[†*‡§\d]', '', name).strip()
            if (
                name and name not in author_names and 
                2 < len(name) < 60 and "\n" not in name and
                not any(kw in name.lower() for kw in ["abstract", "download", "doi", "keywords", "issn", "volume", "issue", "contents"])
            ):
                author_names.append(name)

        # Fallback to meta tags
        if not author_names:
            meta_authors = driver.find_elements(
                By.CSS_SELECTOR,
                "meta[name='author'], meta[property='article:author'], meta[name='bepress_citation_author'], meta[name='citation_author']"
            )
            for ma in meta_authors:
                val = ma.get_attribute("content")
                if val and val.strip():
                    name = val.strip()
                    # If formatted as 'LastName, FirstName', invert it
                    if "," in name and len(name.split(",")) == 2:
                        parts = [p.strip() for p in name.split(",")]
                        name = f"{parts[1]} {parts[0]}"
                    if name not in author_names and len(name) > 2:
                        author_names.append(name)

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # 3. Publication Year
    try:
        date_str = "N/A"
        # Check volume/issue link e.g. <a href=".../vol11" ...>Vol. 11 (2025)</a>
        for vol_sel in ["a[href*='/vol']", "a.ignore", "div#publication_date", "p.date"]:
            elems = driver.find_elements(By.CSS_SELECTOR, vol_sel)
            for el in elems:
                txt = el.text.strip()
                match = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                if match:
                    date_str = match.group(1)
                    break
            if date_str != "N/A":
                break

        # Check meta tags
        if date_str == "N/A":
            for meta_sel in [
                "meta[name='bepress_citation_date']",
                "meta[name='bepress_citation_online_date']",
                "meta[name='citation_date']",
                "meta[name='citation_publication_date']"
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
            "div#abstract p",
            "div#abstract",
            "div[id*='abstract'] p",
            "div[id*='abstract']",
            "section#abstract p",
            "section#abstract"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                for el in elems:
                    t = el.text.strip()
                    if len(t) > 60:
                        raw_text = t
                        break
                if raw_text:
                    break

        if not raw_text:
            try:
                meta_abs = driver.find_element(
                    By.CSS_SELECTOR,
                    "meta[name='description'], meta[property='og:description'], meta[name='citation_abstract']"
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

    # 5. Crossref Fallback if needed
    cur_title = data.get("title", "").strip().lower()
    title_bad = cur_title in [
        "uokerbala", "kijoms", "just a moment...", "are you a robot", "attention required", ""
    ] or cur_title.startswith("www.")
    
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')

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
    if cur_title_final in ["uokerbala", "kijoms", "just a moment...", ""] or cur_title_final.startswith("www."):
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_ojs_data(driver, item=None):
    """
    Extracts structured paper details from Open Journal Systems (OJS) and TWIST Journal (twistjournal.net).
    - Title: h1.page_title, h1.article-title, h1
    - Authors: ul.authors li span.name, span.name, div.authors span.name
    - Publication Year: a[href*='/issue/view/'], span.issue-date, span.published-date, meta citation_date
    - Abstract: div.article-abstract p, section.item.abstract p, div.abstract p, p
    - Fallback: Crossref / OpenAlex DOI & Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "h1.page_title", "h1.article-title", "h1.entry-title", "h1[class*='page_title']", "h1"
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
            "ul.authors li span.name, span.name, div.authors span.name, a.author-name, span.author"
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

        # Strategy B: Find text in issue links e.g. <a href=".../issue/view/17">Vol. 19 No. 4 (2024)</a>
        if date_str == "N/A":
            issue_elems = driver.find_elements(By.CSS_SELECTOR, "a[href*='/issue/view/'], div.item.issue, div.published")
            for el in issue_elems:
                txt = el.text.strip()
                match = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                if match:
                    date_str = match.group(1)
                    break

        # Strategy C: General fallback across text
        if date_str == "N/A":
            body_text = driver.find_element(By.TAG_NAME, "body").text
            match = re.search(r'\b(19\d\d|20\d\d)\b', body_text)
            if match:
                date_str = match.group(1)

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div.article-abstract p",
            "section.item.abstract p",
            "div.abstract p",
            "section.item.abstract",
            "div.article-abstract",
            "div[class*='abstract'] p",
            "div[class*='abstract']"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                p_texts = [e.text.strip() for e in elems if len(e.text.strip()) > 20]
                if p_texts:
                    raw_text = "\n\n".join(p_texts)
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
        "twist", "twistjournal", "twistjournal.net", "just a moment...", "are you a robot", "attention required", ""
    ] or cur_title.startswith("www.") or "checking your browser" in cur_title or "cloudflare" in cur_title
    
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
    if cur_title_final in ["twist", "twistjournal", "twistjournal.net", "just a moment...", ""] or cur_title_final.startswith("www.") or "checking your browser" in cur_title_final or "cloudflare" in cur_title_final:
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_biofuel_data(driver, item=None):
    """
    Extracts structured paper details from Biofuel Research Journal (biofueljournal.com / Sinaweb).
    - Title: span.article_title, h1.article_title, span[class*='article_title'], h1
    - Authors: div[dir='ltr'] a[href*='_action=article&au='], a[href*='_au='], div.author-list a
    - Publication Year: DOI link / text (e.g. 10.18331/BRJ2026.13.2.2 -> 2026), meta citation_date
    - Abstract: div#dv_ar_abs, div.padding_abstract, div[id*='abs'], meta citation_abstract
    - Fallback: Crossref / OpenAlex DOI & Title resolution
    """
    data = {}

    # 1. Title
    try:
        title_elem = None
        for sel in [
            "span.article_title", "h1.article_title", "span[class*='article_title']",
            "h1.page_title", "h1.article-title", "h1"
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
            "div[dir='ltr'] a[href*='_action=article&au='], a[href*='_au='], div.author-list a, a[href*='au=']"
        )
        for elem in author_elements:
            name = elem.text.strip()
            # Normalize double spaces
            name = re.sub(r'\s+', ' ', name)
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
        # Strategy A: Check DOI in page or link e.g. BRJ2026 -> 2026 or standard DOI
        cur_url = driver.current_url or ""
        page_html = driver.page_source or ""
        doi_match = re.search(r'10\.18331/BRJ(19\d\d|20\d\d)\.', page_html)
        if doi_match:
            date_str = doi_match.group(1)

        # Strategy B: Check meta tags
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

        # Strategy C: General regex on DOI anchor links
        if date_str == "N/A":
            doi_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='doi.org/10.']")
            for dl in doi_links:
                txt = dl.text.strip() + " " + (dl.get_attribute("href") or "")
                match = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                if match:
                    date_str = match.group(1)
                    break

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # 4. Abstract
    try:
        raw_text = ""
        for abs_sel in [
            "div#dv_ar_abs",
            "div.padding_abstract",
            "div[id*='dv_ar_abs']",
            "div[class*='padding_abstract']",
            "div.abstract",
            "div#abstract"
        ]:
            elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
            if elems and any(e.text.strip() for e in elems):
                p_elems = elems[0].find_elements(By.CSS_SELECTOR, "p")
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
        "biofuel", "biofuel research journal", "biofueljournal.com", "just a moment...", "are you a robot", "attention required", ""
    ] or cur_title.startswith("www.")
    
    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
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
    if cur_title_final in ["biofuel", "biofuel research journal", "biofueljournal.com", "just a moment...", ""] or cur_title_final.startswith("www."):
        if isinstance(item, dict) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")

    return data

def extract_pmc_data(driver, item=None):
    """
    Extracts paper details from PubMed Central (PMC / NCBI) using e-utilities and page selectors.
    """
    import requests
    data = {}
    url = driver.current_url or (item.get("link", "") if isinstance(item, dict) else "")
    pmc_id_match = re.search(r'PMC(\d+)', url, re.I)
    pmc_id = pmc_id_match.group(1) if pmc_id_match else None

    # Strategy 1: NCBI E-utilities XML API
    if pmc_id:
        try:
            api_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmc_id}&retmode=xml"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get(api_url, headers=headers, timeout=12)
            if resp.status_code == 200 and resp.text:
                xml = resp.text
                # Title
                t_m = re.search(r'<article-title[^>]*>(.*?)</article-title>', xml, re.DOTALL)
                if t_m:
                    data["title"] = clean_title_text(re.sub(r'<[^>]+>', '', t_m.group(1)).strip())
                # Authors
                auth_list = []
                contrib_matches = re.findall(r'<contrib[^>]*contrib-type=["\']author["\'][^>]*>(.*?)</contrib>', xml, re.DOTALL)
                for c in contrib_matches:
                    sur = re.search(r'<surname[^>]*>(.*?)</surname>', c, re.DOTALL)
                    giv = re.search(r'<given-names[^>]*>(.*?)</given-names>', c, re.DOTALL)
                    if sur:
                        s_txt = re.sub(r'<[^>]+>', '', sur.group(1)).strip()
                        g_txt = re.sub(r'<[^>]+>', '', giv.group(1)).strip() if giv else ""
                        full_a = f"{g_txt} {s_txt}".strip() if g_txt else s_txt
                        if full_a and full_a not in auth_list:
                            auth_list.append(full_a)
                if auth_list:
                    data["authors"] = auth_list
                # Year
                y_m = re.search(r'<pub-date[^>]*>.*?<year[^>]*>(\d{4})</year>', xml, re.DOTALL)
                if y_m:
                    data["published_date"] = y_m.group(1)
                # Abstract
                abs_m = re.search(r'<abstract[^>]*>(.*?)</abstract>', xml, re.DOTALL)
                if abs_m:
                    raw_abs = re.sub(r'<[^>]+>', ' ', abs_m.group(1))
                    raw_abs = re.sub(r'\s+', ' ', raw_abs).strip()
                    if raw_abs:
                        data["abstract"] = format_abstract_text(f"Abstract\n\n{raw_abs}")
        except Exception:
            pass

    # Strategy 2: Page Elements Fallback if API was missed or incomplete
    if not data.get("title") or data.get("title") in ["N/A", ""]:
        for t_sel in ["h1.content-title", "h1.part-title", "h1.title", "h1"]:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, t_sel)
                if elems and elems[0].text.strip():
                    data["title"] = clean_title_text(elems[0].text.strip())
                    break
            except Exception:
                pass

    if not data.get("authors"):
        try:
            a_elems = driver.find_elements(By.CSS_SELECTOR, "div.authors-list a, div.contrib-group a, a.full-name")
            names = [e.text.strip() for e in a_elems if len(e.text.strip()) > 2 and not e.text.strip().isdigit()]
            if names:
                data["authors"] = names
        except Exception:
            pass

    if not data.get("published_date") or data.get("published_date") == "N/A":
        try:
            cit_date = driver.find_element(By.CSS_SELECTOR, "meta[name='citation_date'], meta[name='citation_publication_date']").get_attribute("content")
            ym = re.search(r'\b(19\d\d|20\d\d)\b', cit_date or "")
            if ym:
                data["published_date"] = ym.group(1)
        except Exception:
            pass

    if not data.get("abstract") or data.get("abstract") in ["N/A", ""]:
        try:
            for abs_sel in [
                "div.abstract", "div#abstract", "div.tsec.sec", "section.abstract",
                "div[class*='abstract']", "div.abstract-content"
            ]:
                elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
                if elems and elems[0].text.strip():
                    raw_t = elems[0].text.strip()
                    if len(raw_t) > 40:
                        data["abstract"] = format_abstract_text(raw_t if "Abstract" in raw_t else f"Abstract\n\n{raw_t}")
                        break
        except Exception:
            pass

    # Enrich fallback with item data
    if isinstance(item, dict):
        if not data.get("title") or data.get("title") in ["N/A", ""]:
            data["title"] = item.get("title", "N/A")
        if not data.get("authors") and item.get("authors") and item.get("authors") != "N/A":
            data["authors"] = [item.get("authors")]
        if not data.get("published_date") or data.get("published_date") == "N/A":
            data["published_date"] = str(item.get("year", "N/A"))

    return data

def extract_generic_data(driver, item=None):
    """
    Universal generic scholarly extractor for any unmatched domain or journal repository.
    Inspects standard meta tags (citation_*, dc.*, og:*), heading+paragraph DOM elements,
    heading+sibling paragraph elements (e.g. h2 'Abstract' + p), and Crossref/OpenAlex fallback.
    """
    import requests
    data = {
        "title": "N/A",
        "authors": [],
        "published_date": "N/A",
        "abstract": "N/A"
    }

    # --- 1. Title Extraction ---
    try:
        # Check meta tags first
        meta_title_selectors = [
            "meta[name='citation_title']",
            "meta[name='DC.Title']",
            "meta[name='dc.title']",
            "meta[name='bepress_citation_title']",
            "meta[property='og:title']",
            "meta[name='twitter:title']"
        ]
        for sel in meta_title_selectors:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                val = elem.get_attribute("content")
                if val and len(val.strip()) > 5:
                    data["title"] = clean_title_text(val.strip())
                    break
            except Exception:
                pass

        # Fallback to DOM elements
        if data["title"] in ["N/A", ""]:
            for sel in [
                "h1.article-title", "h1.entry-title", "h1.page_title", "h1.title",
                "h1[class*='title']", "h1 a[href*='viewcontent.cgi']", "h1"
            ]:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                if elems and any(e.text.strip() for e in elems):
                    t = [e for e in elems if e.text.strip()][0].text.strip()
                    if len(t) > 5 and "\n" not in t[:50]:
                        data["title"] = clean_title_text(t)
                        break

        # Browser title fallback
        if data["title"] in ["N/A", ""]:
            data["title"] = clean_title_text(driver.title or "")
    except Exception:
        pass

    # --- 2. Authors Extraction ---
    try:
        author_names = []
        meta_author_selectors = [
            "meta[name='citation_author']",
            "meta[name='DC.Creator']",
            "meta[name='dc.creator']",
            "meta[name='bepress_citation_author']",
            "meta[name='author']"
        ]
        for sel in meta_author_selectors:
            meta_elems = driver.find_elements(By.CSS_SELECTOR, sel)
            for me in meta_elems:
                val = me.get_attribute("content")
                if val and val.strip():
                    name = val.strip()
                    if "," in name and len(name.split(",")) == 2:
                        parts = [p.strip() for p in name.split(",")]
                        name = f"{parts[1]} {parts[0]}"
                    if name not in author_names and 2 < len(name) < 70 and not name.isdigit():
                        author_names.append(name)
            if author_names:
                break

        # Fallback to DOM author classes
        if not author_names:
            dom_author_selectors = [
                "ul.authors li span.name", "span.author-name", "a.author-name",
                "div.author-list a", "div.authors span", "div[class*='author'] a"
            ]
            for sel in dom_author_selectors:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in elems:
                    t = el.text.strip()
                    t = re.sub(r'https?://[^\s]+', '', t)
                    t = re.sub(r'[\w\.-]+@[\w\.-]+', '', t)
                    t = re.sub(r'[†*‡§\d]', '', t).strip()
                    if t and t not in author_names and 2 < len(t) < 60 and "\n" not in t:
                        author_names.append(t)
                if author_names:
                    break

        data["authors"] = author_names
    except Exception:
        data["authors"] = []

    # --- 3. Publication Year Extraction ---
    try:
        date_str = "N/A"
        meta_date_selectors = [
            "meta[name='citation_publication_date']",
            "meta[name='citation_date']",
            "meta[name='citation_online_date']",
            "meta[name='DC.Date']",
            "meta[name='dc.date']",
            "meta[name='bepress_citation_date']",
            "meta[property='article:published_time']"
        ]
        for sel in meta_date_selectors:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                val = elem.get_attribute("content")
                if val:
                    ym = re.search(r'\b(19\d\d|20\d\d)\b', val)
                    if ym:
                        date_str = ym.group(1)
                        break
            except Exception:
                pass

        if date_str == "N/A":
            # Search URL or DOM text for 4-digit year
            ym = re.search(r'/(19\d\d|20\d\d)[/-]', driver.current_url or "")
            if ym:
                date_str = ym.group(1)

        data["published_date"] = date_str
    except Exception:
        data["published_date"] = "N/A"

    # --- 4. Abstract Extraction ---
    try:
        raw_text = ""
        # Check standard meta citation_abstract first
        for sel in ["meta[name='citation_abstract']", "meta[name='description']", "meta[property='og:description']"]:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                val = elem.get_attribute("content") or ""
                if len(val.strip()) > 60:
                    raw_text = val.strip()
                    break
            except Exception:
                pass

        # Check heading pattern: <h2 class="field-heading">Abstract</h2> followed by <p> tag or sibling
        if not raw_text or len(raw_text) < 50:
            try:
                heading_script = """
                var headings = document.querySelectorAll('h1, h2, h3, h4, strong, b, div, span');
                for (var i = 0; i < headings.length; i++) {
                    var txt = (headings[i].textContent || '').trim().toLowerCase();
                    if (txt === 'abstract' || txt === 'summary') {
                        var next = headings[i].nextElementSibling;
                        while (next) {
                            if (next.tagName.toLowerCase() === 'p' && next.textContent.trim().length > 40) {
                                return next.textContent.trim();
                            }
                            if (next.querySelector('p')) {
                                var innerP = next.querySelector('p');
                                if (innerP && innerP.textContent.trim().length > 40) {
                                    return innerP.textContent.trim();
                                }
                            }
                            if (next.textContent.trim().length > 50) {
                                return next.textContent.trim();
                            }
                            next = next.nextElementSibling;
                        }
                        // Check parent's next element or parent's paragraph
                        var parentNext = headings[i].parentElement ? headings[i].parentElement.nextElementSibling : null;
                        if (parentNext && parentNext.textContent.trim().length > 50) {
                            return parentNext.textContent.trim();
                        }
                    }
                }
                return null;
                """
                dom_sibling_abs = driver.execute_script(heading_script)
                if dom_sibling_abs and len(dom_sibling_abs.strip()) > 50:
                    raw_text = dom_sibling_abs.strip()
            except Exception:
                pass

        # Check dedicated abstract container selectors
        if not raw_text or len(raw_text) < 50:
            for abs_sel in [
                "div#abstract p", "div.abstract p", "section.abstract p", "section#abstract p",
                "div.article-abstract p", "section.item.abstract p", "div.padding_abstract",
                "div#dv_ar_abs", "div.abstract-content", "div.abstract", "div#abstract",
                "section.abstract", "section#abstract", "div[class*='abstract']"
            ]:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, abs_sel)
                    if elems and any(e.text.strip() for e in elems):
                        p_texts = [e.text.strip() for e in elems if len(e.text.strip()) > 30]
                        if p_texts:
                            cand = "\n\n".join(p_texts)
                            if len(cand) > 50:
                                raw_text = cand
                                break
                except Exception:
                    pass

        if raw_text:
            if "Abstract" in raw_text:
                raw_text = raw_text[raw_text.find("Abstract"):]
            else:
                raw_text = "Abstract\n\n" + raw_text
            data["abstract"] = format_abstract_text(raw_text)
        else:
            data["abstract"] = "N/A"
    except Exception:
        data["abstract"] = "N/A"

    # --- 5. Crossref / DOI Fallback Enrichment ---
    cur_title = data.get("title", "").strip().lower()
    title_bad = (
        not data.get("title") or
        any(err_kw in cur_title for err_kw in [
            "just a moment...", "are you a robot", "attention required", "error",
            "403 forbidden", "404 not found", "n/a", "this site can’t be reached",
            "this site can't be reached", "err_connection", "err_name_not_resolved",
            "problem loading page", "server not found", "access denied"
        ]) or
        cur_title.startswith("www.") or
        "cloudflare" in cur_title or
        "checking your browser" in cur_title
    )

    if not data.get("authors") or title_bad or data.get("published_date") == "N/A" or data.get("abstract") in ["N/A", "", "Abstract"]:
        try:
            item_link = item.get("link", "") if isinstance(item, dict) else ""
            cur_url = driver.current_url or ""
            doc_link = item.get("document_link", "") if isinstance(item, dict) else ""
            target_str = f"{cur_url} {item_link} {doc_link}"
            doi = None
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', target_str)
            if doi_match:
                doi = doi_match.group(0).rstrip('/')
                doi = re.sub(r'\.(?:abstract|full|pdf|article|html)$', '', doi, flags=re.I)

            cand_title = item.get("title") if isinstance(item, dict) else None
            if not doi and cand_title and cand_title not in ["No Title", "Direct URL"]:
                try:
                    import urllib.parse
                    q = urllib.parse.quote_plus(cand_title)
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                    cr_s = requests.get(f"https://api.crossref.org/works?query.title={q}&rows=1", headers=headers, timeout=8)
                    if cr_s.status_code == 200 and cr_s.json().get("message", {}).get("items"):
                        doi = cr_s.json()["message"]["items"][0].get("DOI")
                except Exception:
                    pass

            if doi:
                doi = doi.rstrip('/')
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

    # Safety fallback: preserve input.txt information if extraction missed fields
    if isinstance(item, dict):
        if (data.get("title") in ["N/A", ""] or title_bad) and item.get("title") and item.get("title") not in ["No Title", "Direct URL"]:
            data["title"] = item.get("title")
        if not data.get("authors") and item.get("authors") and item.get("authors") != "N/A":
            data["authors"] = [item.get("authors")]
        if data.get("published_date") in ["N/A", "None", None] and item.get("year") and str(item.get("year")) != "N/A":
            data["published_date"] = str(item.get("year"))

    return data

def extract_pdf_data(pdf_url, item=None):
    """
    Downloads and extracts text from a direct PDF URL using pypdf.
    Parses Title, Authors, Published Year, and Abstract from the first pages of the PDF.
    Enriches with Crossref if a DOI is detected in the PDF text.
    """
    import requests
    data = {
        "title": item.get("title") if (item and item.get("title") not in ["No Title", "Direct URL"]) else "N/A",
        "authors": [item.get("authors")] if (item and item.get("authors") and item.get("authors") != "N/A") else [],
        "published_date": str(item.get("year")) if (item and item.get("year") and item.get("year") != "N/A") else "N/A",
        "abstract": "N/A"
    }

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "application/pdf,*/*"
        }
        resp = requests.get(pdf_url, headers=headers, timeout=25, allow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return data

        pdf_bytes = resp.content
        full_text = ""
        first_page_text = ""

        if HAS_PYPDF:
            try:
                reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                num_pages = len(reader.pages)
                # Read up to the first 3 pages
                pages_to_read = min(3, num_pages)
                for p_num in range(pages_to_read):
                    page_text = reader.pages[p_num].extract_text() or ""
                    if p_num == 0:
                        first_page_text = page_text
                    full_text += "\n" + page_text

                # Check PDF document metadata
                if reader.metadata:
                    meta_title = reader.metadata.title
                    if meta_title and len(meta_title.strip()) > 5 and not meta_title.lower().endswith(".pdf"):
                        if data["title"] == "N/A":
                            data["title"] = clean_title_text(meta_title)
                    meta_author = reader.metadata.author
                    if meta_author and not data["authors"]:
                        data["authors"] = [clean_author_name(a.strip()) for a in meta_author.split(",") if a.strip()]
            except Exception:
                pass

        # 1. Abstract extraction from PDF text
        if full_text:
            text_norm = re.sub(r'[ \t]+', ' ', full_text)
            # Find Abstract section heading (handles both 'Abstract' and spaced 'A B S T R A C T')
            match_abs = re.search(r'(?is)\b(?:A\s*B\s*S\s*T\s*R\s*A\s*C\s*T|Abstract)\b[:\.\s—–-]*\n*(.*?)(?=\n\s*(?:(?:1[\.\s]+)?Introduction|Keywords|Index Terms|Background|Methods|Key words|A\s*R\s*T\s*I\s*C\s*L\s*E\s*I\s*N\s*F\s*O)|\Z)', text_norm)
            if match_abs:
                raw_abs = match_abs.group(1).strip()
                # Clean up multiple newlines or hyphenated words
                raw_abs = re.sub(r'-\n\s*', '', raw_abs)
                raw_abs = re.sub(r'\s+', ' ', raw_abs).strip()
                if len(raw_abs) >= 50:
                    data["abstract"] = format_abstract_text(f"Abstract\n\n{raw_abs}")

            # 2. Year extraction
            if data["published_date"] == "N/A":
                year_match = re.search(r'\b(20\d\d|19\d\d)\b', first_page_text[:1500])
                if year_match:
                    data["published_date"] = year_match.group(1)

            # 3. DOI detection & Crossref Enrichment
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', full_text[:4000])
            if doi_match:
                doi = doi_match.group(0).rstrip('.;,)')
                enrich_with_crossref(data, doi)

    except Exception:
        pass

    return data

def load_links_from_json(json_path):
    """
    Reads a JSON or text file and extracts paper metadata.
    Strictly picks the HTML article 'link' and never takes 'documentLink' or links ending in .pdf.
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

        def is_pdf_url(url_str):
            if not url_str or not isinstance(url_str, str):
                return True
            u_clean = url_str.strip().lower()
            return u_clean.endswith(".pdf") or ".pdf?" in u_clean or "/content/pdf/" in u_clean

        def extract_item_info(idx, item):
            if isinstance(item, dict):
                # Always take "link" - NEVER use "documentLink"
                target_url = item.get("link")
                if not target_url or not isinstance(target_url, str) or not target_url.strip():
                    return None
                
                target_url = target_url.strip()

                return {
                    "index": idx,
                    "title": item.get("title", "No Title"),
                    "link": target_url,
                    "documentLink": item.get("documentLink", ""),
                    "cidCode": item.get("cidCode", ""),
                    "relatedArticlesLink": item.get("relatedArticlesLink", ""),
                    "authors": item.get("authors", "N/A"),
                    "source": item.get("source", "N/A"),
                    "year": item.get("year", "N/A"),
                    "citations": item.get("citations", "N/A")
                }
            elif isinstance(item, str):
                s = item.strip()
                if s.startswith("http://") or s.startswith("https://"):
                    return {
                        "index": idx,
                        "title": "Direct URL",
                        "link": s
                    }
            return None

        try:
            data = json.loads(content)
            if isinstance(data, list):
                for idx, item in enumerate(data):
                    info = extract_item_info(len(links), item)
                    if info:
                        links.append(info)
            elif isinstance(data, dict):
                info = extract_item_info(0, data)
                if info:
                    links.append(info)
        except json.JSONDecodeError:
            # Handle JSON Lines or raw text file lines
            for idx, line in enumerate(content.splitlines()):
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        info = extract_item_info(len(links), item)
                        if info:
                            links.append(info)
                    except Exception:
                        # Raw line might be a regex for "link": "http..." or direct URL
                        match = re.search(r'"link"\s*:\s*"([^"]+)"', line)
                        if match:
                            url_val = match.group(1).strip()
                            if not is_pdf_url(url_val):
                                links.append({
                                    "index": len(links),
                                    "title": "Direct URL",
                                    "link": url_val
                                })
                        elif (line.startswith("http://") or line.startswith("https://")) and not is_pdf_url(line):
                            links.append({
                                "index": len(links),
                                "title": "Direct URL",
                                "link": line
                            })

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

    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    csv_filename = os.path.join(script_dir, "scraped_papers.csv")
    fieldnames = ["SL NO.", "Title", "Authors", "Published Year", "Abstract", "Paper Link"]

    def append_paper_to_csv(sl_no, url_target, data_dict):
        try:
            # If title is missing, empty, bot verification, or generic domain error, fallback to placing the URL or genuine title
            bot_phrases = ['are you a robot', 'just a moment', 'cloudflare', 'attention required', 'access denied', '403 forbidden', 'security service to protect']
            if not raw_title or not str(raw_title).strip() or str(raw_title).strip().lower() in ["n/a", "none", "no title"] or any(bp in str(raw_title).lower() for bp in bot_phrases):
                final_title = url_target
            else:
                final_title = str(raw_title).strip()

            raw_abstract = data_dict.get("abstract") if data_dict else None
            # If abstract is missing, empty, bot challenge, or N/A, save the link on that abstract section
            if not raw_abstract or not str(raw_abstract).strip() or str(raw_abstract).strip().lower() in ["n/a", "none", "abstract"] or any(bp in str(raw_abstract).lower() for bp in bot_phrases):
                abstract = url_target
            else:
                abstract = str(raw_abstract).strip()

            # Filter non-English papers
            if not is_text_english(final_title, abstract):
                print(f"[!] 🌐 Non-English paper detected ('{final_title[:45]}...'). Skipping from CSV as requested.")
                return False

            raw_authors = data_dict.get("authors") if data_dict else None
            if isinstance(raw_authors, list):
                authors = ", ".join(str(a).strip() for a in raw_authors if str(a).strip())
            elif raw_authors:
                authors = str(raw_authors).strip()
            else:
                authors = "N/A"

            pub_year = data_dict.get("published_date") or data_dict.get("year") or "N/A" if data_dict else "N/A"
            pub_year = str(pub_year).strip()

            written = False
            for attempt in range(5):
                try:
                    with open(csv_filename, mode="a", newline="", encoding="utf-8-sig") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writerow({
                            "SL NO.": sl_no,
                            "Title": final_title,
                            "Authors": authors,
                            "Published Year": pub_year,
                            "Abstract": abstract,
                            "Paper Link": url_target
                        })
                        f.flush()
                    written = True
                    break
                except PermissionError:
                    if attempt == 0:
                        print(f"[!] Warning: '{csv_filename}' is locked by another process (e.g. Excel). Please close it. Retrying...")
                    time.sleep(1.0)
                except Exception as ex_write:
                    print(f"[!] Error writing to CSV: {ex_write}")
                    break

            if written:
                print(f"[+] 💾 Saved item [{sl_no}/{total}] to {csv_filename}")
            else:
                print(f"[!] Could not write item [{sl_no}/{total}] to CSV after retries.")
        except Exception as e:
            print(f"[!] Error in append_paper_to_csv: {e}")

    # Initialize / overwrite CSV header at the beginning of the run
    for attempt in range(5):
        try:
            with open(csv_filename, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            break
        except PermissionError:
            if attempt == 0:
                print(f"[!] Warning: '{csv_filename}' is locked. Please close it in Excel. Retrying...")
            time.sleep(1.0)
        except Exception as e:
            print(f"[!] Warning: Could not create CSV header: {e}")
            break

    results = []
    current_driver = None
    current_driver_type = None
    processed_domain_count = 0

    def get_fresh_driver(driver_type):
        if driver_type == "captcha_humanoid":
            print("[*] 🛡️ Initializing Undetected Humanoid Browser (Visible Mode for Cell / Wiley / ScienceDirect / RSC / ACS / Cambridge / Bentham)...")
            return create_humanoid_driver(headless=False)
        else:
            print("[*] ⚡ Initializing Fast Lite Browser (Silent Headless Mode: Springer / Frontiers / MDPI / Nature / De Gruyter)...")
            return create_lite_driver(headless=True)

    try:
        for item in link_items:
            sl_no = len(results) + 1
            url = item["link"]
            parsed_domain = urlparse(url).netloc.lower()
            needs_captcha_humanoid = ("cell.com" in parsed_domain) or ("wiley.com" in parsed_domain) or ("sciencedirect.com" in parsed_domain) or ("tandfonline.com" in parsed_domain) or ("benthamdirect.com" in parsed_domain) or ("sagepub.com" in parsed_domain) or ("aip.org" in parsed_domain) or ("cambridge.org" in parsed_domain) or ("rsc.org" in parsed_domain) or ("acs.org" in parsed_domain) or ("emerald.com" in parsed_domain) or ("ascelibrary.org" in parsed_domain) or ("authorea.com" in parsed_domain) or ("medrxiv.org" in parsed_domain) or ("biorxiv.org" in parsed_domain) or ("twistjournal.net" in parsed_domain) or ("uokerbala.edu.iq" in parsed_domain) or ("kijoms" in parsed_domain)

            required_type = "captcha_humanoid" if needs_captcha_humanoid else "lite"

            # Periodic recycling: restart browser every 40 items to clear memory and prevent ChromeDriver disconnection crashes
            should_recycle = (processed_domain_count >= 40)
            if current_driver_type != required_type or should_recycle or current_driver is None:
                if current_driver:
                    try:
                        current_driver.quit()
                    except Exception:
                        pass
                    current_driver = None

                if should_recycle:
                    print(f"[*] ♻️ Recycling WebDriver session after {processed_domain_count} pages to free RAM and prevent session disconnection...")
                    processed_domain_count = 0

                current_driver = get_fresh_driver(required_type)
                current_driver_type = required_type

            print(f"------------------------------------------------------------------")
            print(f"[+] ITEM [{item['index'] + 1}/{total}]")
            print(f"[+] Target URL: {url}")
            print(f"------------------------------------------------------------------")
            
            # 1. Guard against non-HTTP or "N/A" links
            if not url or not (url.startswith("http://") or url.startswith("https://")):
                print(f"[!] Target URL is not a valid web URL ({url}). Saving to CSV and moving to next link...")
                fallback_data = {
                    "title": item.get("title") if (item.get("title") and item.get("title") != "No Title") else url,
                    "authors": [item.get("authors")] if (item.get("authors") and item.get("authors") != "N/A") else [],
                    "published_date": str(item.get("year")) if (item.get("year") and item.get("year") != "N/A") else "N/A",
                    "abstract": "N/A"
                }
                append_paper_to_csv(sl_no, url, fallback_data)
                results.append({
                    "url": url,
                    "scraped_data": fallback_data,
                    "status": "skipped"
                })
                continue

            # 2. Check if this is a direct PDF link
            url_clean = url.strip().lower()
            is_pdf = url_clean.endswith(".pdf") or ".pdf?" in url_clean or "/content/pdf/" in url_clean or "/files/rs-" in url_clean

            if is_pdf:
                print(f"[*] 📄 Direct PDF Link Detected -> Extracting PDF metadata & Abstract directly...")
                try:
                    start_time = time.time()
                    scraped_data = extract_pdf_data(url, item=item)
                    elapsed = time.time() - start_time
                    print(f"[+] PDF Processed & Extracted in {elapsed:.2f} seconds!")

                    print(f"\n--- [ PDF Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                    append_paper_to_csv(sl_no, url, scraped_data)
                    results.append({
                        "url": url,
                        "scraped_data": scraped_data,
                        "status": "success"
                    })
                except Exception as pdf_ex:
                    print(f"[!] Failed to parse PDF {url}: {pdf_ex}")
                    append_paper_to_csv(sl_no, url, {})
                    results.append({
                        "url": url,
                        "status": "failed",
                        "error": str(pdf_ex)
                    })
                continue

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
                        "h1.title", "h1[class*='article-title']", "p.articleBody_abstractText", "div.al-authors-list",
                        "h1 a[href*='viewcontent.cgi']", "p#title", "div#abstract p", "div#abstract"
                    ]
                    found = wait_for_captcha_and_content(current_driver, target_selectors, timeout=35)
                    if found:
                        humanoid_mouse_and_scroll(current_driver)
                else:
                    # For fast lite sites (Springer, MDPI, Frontiers, Nature, De Gruyter Brill), wait up to 6 seconds for title/body element
                    fast_selectors = [
                        "h1.highwire-cite-title", "span.highwire-citation-authors", "div.section.abstract",
                        "span.title_jmi", "div#authorString", "div.article-authors",
                        "h1#artTitle", "div.abstract-content",
                        "h1.title-dgb", "h1[class*='title-dgb']", "h1.c-article-title",
                        "h1[data-test='article-title']", "h1.title", "h1[itemprop='name']",
                        "h1.ArticleDetailsV4__main__title", "h1.document-title", "span.abstract-text-content",
                        "h1[class*='font-extrabold']", "div.abstract-text", "div[class*='abstract-text']",
                        "h1.page_title", "section.item.abstract", "div.article-abstract",
                        "span.article_title", "div#dv_ar_abs", "div.padding_abstract",
                        "h1 a[href*='viewcontent.cgi']", "div#abstract p", "div#abstract", "h1"
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

                # Update current URL and parsed domain in case of redirects
                final_url = current_driver.current_url or url
                parsed_domain = urlparse(final_url).netloc.lower() or parsed_domain

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

                elif "rsc.org" in parsed_domain or "acs.org" in parsed_domain:
                    source_label = "ACS Publications" if "acs.org" in parsed_domain else "Royal Society of Chemistry"
                    print(f"[*] {source_label} Domain Detected -> Extracting Article Elements...")
                    scraped_data = extract_rsc_data(current_driver, item=item)

                    print(f"\n--- [ {source_label} Extracted Data ] ---")
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

                elif "twistjournal.net" in parsed_domain or "twistjournal" in parsed_domain or "/article/view/" in url:
                    print(f"[*] TWIST / OJS Domain Detected -> Extracting Article Elements...")
                    scraped_data = extract_ojs_data(current_driver, item=item)

                    print(f"\n--- [ TWIST / OJS Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "biofueljournal.com" in parsed_domain or "biofuel" in parsed_domain or "_action=article" in url:
                    print(f"[*] Biofuel Research Journal / Sinaweb Domain Detected -> Extracting Article Elements...")
                    scraped_data = extract_biofuel_data(current_driver, item=item)

                    print(f"\n--- [ Biofuel Research Journal Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "uokerbala.edu.iq" in parsed_domain or "kijoms" in parsed_domain or "viewcontent.cgi" in url:
                    print(f"[*] Karbala International Journal / Digital Commons Detected -> Extracting Article Elements...")
                    scraped_data = extract_bepress_data(current_driver, item=item)

                    print(f"\n--- [ Karbala International Journal Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                elif "pmc.ncbi.nlm.nih.gov" in parsed_domain or "ncbi.nlm.nih.gov" in parsed_domain or "/pmc/" in url:
                    print(f"[*] PMC / NCBI Domain Detected -> Extracting PubMed Central Elements...")
                    scraped_data = extract_pmc_data(current_driver, item=item)

                    print(f"\n--- [ PMC / NCBI Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                else:
                    print(f"[*] Standard / Repository Domain Detected -> Extracting Generic Article Elements...")
                    scraped_data = extract_generic_data(current_driver, item=item)

                    print(f"\n--- [ Generic Scholarly Extracted Data ] ---")
                    print(f"📌 Title          : {scraped_data.get('title')}")
                    print(f"👥 Author Names   : {', '.join(scraped_data.get('authors', []))}")
                    print(f"📅 Published Date : {scraped_data.get('published_date')}")
                    print(f"\n📖 Abstract (Formatted Plain Text):\n\n{scraped_data.get('abstract')}\n")

                processed_domain_count += 1
                append_paper_to_csv(sl_no, url, scraped_data)
                results.append({
                    "url": url,
                    "scraped_data": scraped_data,
                    "status": "success"
                })

            except Exception as ex:
                print(f"[!] Failed to load {url}: {ex}")
                # Fallback to input metadata if available rather than blank
                fallback_data = {
                    "title": item.get("title") if (item.get("title") and item.get("title") != "No Title") else url,
                    "authors": [item.get("authors")] if (item.get("authors") and item.get("authors") != "N/A") else [],
                    "published_date": str(item.get("year")) if (item.get("year") and item.get("year") != "N/A") else "N/A",
                    "abstract": url
                }
                append_paper_to_csv(sl_no, url, fallback_data)
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": str(ex)
                })

                # Check if the WebDriver crashed or session was disconnected
                err_msg = str(ex).lower()
                is_driver_dead = any(dead_kw in err_msg for dead_kw in [
                    "disconnected", "not connected to devtools", "invalid session",
                    "chrome not reachable", "session not created", "gethandleverifier",
                    "broken pipe", "connection refused", "remotedisconnected", "target frame detached"
                ])
                if is_driver_dead:
                    print(f"[*] ⚠️ Browser session crashed / disconnected. Performing clean restart of {required_type} driver...")
                    try:
                        current_driver.quit()
                    except Exception:
                        pass
                    current_driver = None
                    try:
                        current_driver = get_fresh_driver(required_type)
                        current_driver_type = required_type
                        processed_domain_count = 0
                        print(f"[+] 🚀 Browser restarted successfully! Continuing scraping seamlessly...")
                    except Exception as restart_err:
                        print(f"[!] Failed to reboot browser: {restart_err}")
    finally:
        print(f"\n==================================================================")
        print(f"[*] SCRAPING COMPLETED | Closing Browser Session")
        print(f"==================================================================\n")
        if current_driver:
            try:
                current_driver.quit()
            except Exception:
                pass

        print(f"[+] 📊 Results continuously saved to CSV: {os.path.abspath(csv_filename)}")

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
