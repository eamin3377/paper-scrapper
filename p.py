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
        options.add_argument(f"user-agent={user_agent}")
        options.add_argument("--lang=en-US,en")
        options.page_load_strategy = 'eager'
        
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

def wait_for_captcha_and_content(driver, selectors, timeout=15):
    """
    Polls the DOM rapidly. As soon as any target article element appears after CAPTCHA,
    and page title is no longer 'Are you a robot?', returns True immediately.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            title = driver.title.lower()
            if "are you a robot" in title or "just a moment" in title or "cloudflare" in title:
                time.sleep(0.5)
                continue

            for selector in selectors:
                elems = driver.find_elements(By.CSS_SELECTOR, selector)
                if elems and any(e.text.strip() for e in elems):
                    return True
        except Exception:
            pass
        time.sleep(0.4)
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
            needs_captcha_humanoid = ("cell.com" in parsed_domain) or ("wiley.com" in parsed_domain) or ("sciencedirect.com" in parsed_domain) or ("tandfonline.com" in parsed_domain)

            required_type = "captcha_humanoid" if needs_captcha_humanoid else "lite"
            if current_driver_type != required_type:
                if current_driver:
                    try:
                        current_driver.quit()
                    except Exception:
                        pass
                
                if required_type == "captcha_humanoid":
                    print("[*] 🛡️ Initializing Undetected Humanoid Browser (Cell / Wiley / ScienceDirect / TandF Online CAPTCHA Mode)...")
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
                        "span.NLM_article-title", "div.hlFld-Abstract", "div#abstractId1",
                        "span.title-text", "h1.title-text", "div.author-group", "div#abs0001", "div#abss0001",
                        "h1.citation__title", "h1[property='name']", "h1.article-header__title", "h1.article-title",
                        "section.article-section__abstract", "section#author-abstract", "div.article-tools__abstract",
                        "div.abstract", "#abstract", "div.abstract-group", "section[class*='abstract']"
                    ]
                    found = wait_for_captcha_and_content(current_driver, target_selectors, timeout=12)
                    if not found:
                        humanoid_mouse_and_scroll(current_driver)
                        wait_for_captcha_and_content(current_driver, target_selectors, timeout=8)
                else:
                    # For fast lite sites (Springer, MDPI, Frontiers, Nature, De Gruyter Brill), wait up to 6 seconds for title/body element
                    fast_selectors = [
                        "h1.title-dgb", "h1[class*='title-dgb']", "h1.c-article-title",
                        "h1[data-test='article-title']", "h1.title", "h1[itemprop='name']",
                        "h1.ArticleDetailsV4__main__title", "h1.document-title", "span.abstract-text-content", "h1"
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
