import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse

# Ensure stdout handles UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BOT_TITLE_KEYWORDS = [
    'are you a robot', 'just a moment', 'cloudflare', 'attention required',
    'access denied', '403 forbidden', 'robot check', 'security check',
    'proquest platform', 'explore millions of resources'
]

def format_abstract_text(text):
    if not text:
        return "N/A"
    
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Slice text starting from 'Abstract' if present
    if "Abstract" in text:
        text = text[text.find("Abstract"):]
    else:
        text = "Abstract\n\n" + text.strip()

    # Strip out UI buttons/navigation text & Keywords / Graphical Abstract
    text = re.sub(r'(?i)\b(?:first_page|settings|Order Article Reprints|Open Access|Download|Browse Figures|Explore millions of resources from scholarly journals, books, newspapers, videos and more, on the ProQuest Platform\.?)\b', '', text)
    text = re.sub(r'(?is)\bKeywords?:.*$', '', text)
    text = re.sub(r'(?is)\bKey\s+words?:.*$', '', text)
    text = re.sub(r'(?is)\bGraphical\s+Abstract.*$', '', text)
    
    # Insert double newlines before common section keywords
    pattern = r'(\b(?:Abstract|Background:?|Objective:?|Methods:?|Results:?|Conclusions?:?))\s*'
    text = re.sub(pattern, r'\n\n\1 ', text)
    
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text

def is_bad_title(title, link=""):
    if not title or not str(title).strip():
        return True
    t_clean = str(title).strip()
    t_lower = t_clean.lower()
    
    if t_clean == link:
        return True
    if t_lower in ['n/a', 'none', 'no title', 'direct url']:
        return True
    if any(bw in t_lower for bw in BOT_TITLE_KEYWORDS):
        return True
    # If title is just a domain name (e.g. www.tandfonline.com, dl.acm.org, search.informit.org)
    if re.match(r'^(?:www\.)?[a-zA-Z0-9-]+\.(?:com|org|net|edu|gov|io|tr|eg)(?:/[^\s]*)?$', t_clean):
        return True
    # If title is an author list with affiliation numbers (e.g., 'Shuai Yu 1 Yaya Ren 1...')
    if bool(re.search(r'^\s*[A-Z][a-z]+(\s+[A-Z][a-z]+)?\s+1\b', t_clean)) or ('@' in t_clean and '1' in t_clean):
        return True
    return False

def is_bad_abstract(abstract, link=""):
    if not abstract or not str(abstract).strip():
        return True
    a_clean = str(abstract).strip()
    a_lower = a_clean.lower()
    if a_clean == link:
        return True
    if a_lower in ['n/a', 'none', 'abstract']:
        return True
    if len(a_clean) < 40:
        return True
    if any(bw in a_lower for bw in BOT_TITLE_KEYWORDS):
        return True
    return False

def extract_doi(text):
    if not text:
        return None
    match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', text)
    if match:
        doi = match.group(0).rstrip('.;,)/')
        if '%2F' in doi or '%2f' in doi:
            doi = urllib.parse.unquote(doi)
        return doi
    return None

def fetch_crossref(doi=None, title=None):
    headers = {"User-Agent": "AcademicResearchScraper/2.0 (mailto:scholar_research@sust.edu)"}
    if doi:
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode('utf-8', errors='ignore'))
                return d.get("message")
        except Exception:
            pass

    if title and len(title.strip()) > 10:
        clean_t = re.sub(r'[^a-zA-Z0-9\s]', ' ', title)
        query_str = " ".join(clean_t.split()[:12])
        url = f"https://api.crossref.org/works?query.title={urllib.parse.quote(query_str)}&rows=1"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode('utf-8', errors='ignore'))
                items = d.get("message", {}).get("items", [])
                if items:
                    return items[0]
        except Exception:
            pass
    return None

def fetch_openalex(doi=None, title=None):
    headers = {"User-Agent": "AcademicResearchScraper/2.0 (mailto:scholar_research@sust.edu)"}
    if doi:
        url = f"https://api.openalex.org/works/https://doi.org/{doi}?mailto=scholar_research@sust.edu"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode('utf-8', errors='ignore'))
        except Exception:
            pass

    if title and len(title.strip()) > 10:
        clean_t = re.sub(r'[^a-zA-Z0-9\s]', ' ', title)
        query_str = " ".join(clean_t.split()[:10])
        url = f"https://api.openalex.org/works?search={urllib.parse.quote(query_str)}&per-page=1&mailto=scholar_research@sust.edu"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode('utf-8', errors='ignore'))
                res = d.get("results", [])
                if res:
                    return res[0]
        except Exception:
            pass
    return None

def extract_openalex_abstract(oa_item):
    if not oa_item:
        return None
    inv = oa_item.get("abstract_inverted_index")
    if inv:
        words = sorted([(idx, w) for w, idxs in inv.items() for idx in idxs])
        return " ".join([w[1] for w in words]).strip()
    return None

def clean_author_names(author_obj):
    if not author_obj:
        return "N/A"
    if isinstance(author_obj, str):
        return author_obj.strip()
    if isinstance(author_obj, list):
        names = []
        for a in author_obj:
            if isinstance(a, dict):
                g = a.get("given", "").strip()
                f = a.get("family", "").strip()
                full = f"{g} {f}".strip() if g and f else (f or g)
                if full:
                    names.append(full)
            elif isinstance(a, str) and a.strip():
                names.append(a.strip())
        return ", ".join(names) if names else "N/A"
    return "N/A"

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "scraped_papers.csv")
    input_path = os.path.join(script_dir, "input.txt")

    if not os.path.exists(csv_path):
        print(f"[!] File not found: {csv_path}")
        return

    input_items = []
    if os.path.exists(input_path):
        with open(input_path, "r", encoding="utf-8") as f:
            input_items = json.load(f)

    # Build lookup by link and by index
    input_by_link = {}
    for it in input_items:
        if it.get("link"):
            input_by_link[it["link"].strip()] = it

    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        rows = list(csv.DictReader(f))

    print(f"[*] Total rows currently in scraped_papers.csv: {len(rows)}")

    fixed_titles_count = 0
    fixed_abstracts_count = 0

    for idx, row in enumerate(rows):
        sl = row.get("SL NO.", str(idx + 1))
        curr_title = row.get("Title", "").strip()
        curr_abs = row.get("Abstract", "").strip()
        curr_link = row.get("Paper Link", "").strip()
        curr_authors = row.get("Authors", "").strip()
        curr_year = row.get("Published Year", "").strip()

        matched_input = input_by_link.get(curr_link, {})
        orig_title = matched_input.get("title", "")
        orig_doc_link = matched_input.get("documentLink", "")
        orig_authors = matched_input.get("authors", "")
        orig_year = str(matched_input.get("year", ""))

        bad_t = is_bad_title(curr_title, curr_link)
        bad_a = is_bad_abstract(curr_abs, curr_link)

        if not bad_t and not bad_a:
            continue

        print(f"\n[*] Processing Item [{sl}]: Title='{curr_title[:45]}...' (Bad Title: {bad_t}, Bad Abstract: {bad_a})")

        # Determine authentic title candidate
        best_title = None
        if not is_bad_title(orig_title, curr_link):
            best_title = orig_title
        elif not bad_t:
            best_title = curr_title

        # Determine DOI
        doi = extract_doi(curr_link) or extract_doi(orig_doc_link)

        cr_msg = None
        oa_item = None

        # 1. Query Crossref
        if doi:
            cr_msg = fetch_crossref(doi=doi)
            time.sleep(0.3)
        if not cr_msg and best_title:
            cr_msg = fetch_crossref(title=best_title)
            if cr_msg and not doi:
                doi = cr_msg.get("DOI")
            time.sleep(0.3)

        # 2. Query OpenAlex
        if doi or best_title:
            oa_item = fetch_openalex(doi=doi, title=best_title)
            time.sleep(0.3)

        # Fix Title
        new_title = None
        if cr_msg and cr_msg.get("title"):
            t_cand = cr_msg["title"][0] if isinstance(cr_msg["title"], list) else cr_msg["title"]
            if not is_bad_title(t_cand, curr_link):
                new_title = t_cand
        if not new_title and oa_item and oa_item.get("title"):
            t_cand = oa_item.get("title")
            if not is_bad_title(t_cand, curr_link):
                new_title = t_cand
        if not new_title and best_title:
            new_title = best_title

        if new_title and (bad_t or curr_title != new_title):
            row["Title"] = new_title
            fixed_titles_count += 1
            print(f"  [+] Repaired Title: {new_title[:65]}")

        # Fix Authors
        if (not curr_authors or curr_authors in ["N/A", "None", ""]) or curr_authors == curr_link:
            if cr_msg and cr_msg.get("author"):
                row["Authors"] = clean_author_names(cr_msg["author"])
            elif orig_authors and orig_authors != "N/A":
                row["Authors"] = orig_authors

        # Fix Published Year
        if (not curr_year or curr_year in ["N/A", "None", ""]) or curr_year == curr_link:
            if cr_msg and cr_msg.get("created"):
                dp = cr_msg["created"].get("date-parts")
                if dp and dp[0]:
                    row["Published Year"] = str(dp[0][0])
            elif orig_year and orig_year != "N/A":
                row["Published Year"] = orig_year

        # Fix Abstract
        if bad_a:
            new_abs = None
            if cr_msg and cr_msg.get("abstract") and len(cr_msg["abstract"].strip()) > 50:
                new_abs = format_abstract_text(cr_msg["abstract"])
            if not new_abs and oa_item:
                oa_abs = extract_openalex_abstract(oa_item)
                if oa_abs and len(oa_abs.strip()) > 50:
                    new_abs = format_abstract_text(oa_abs)

            if new_abs and not is_bad_abstract(new_abs, curr_link):
                row["Abstract"] = new_abs
                fixed_abstracts_count += 1
                print(f"  [+] Repaired Abstract! Length: {len(new_abs)}")
            else:
                # Store authentic paper link fallback
                row["Abstract"] = curr_link
                print(f"  [-] Retained paper link in abstract: {curr_link[:50]}")

    # Write cleaned rows
    fieldnames = ["SL NO.", "Title", "Authors", "Published Year", "Abstract", "Paper Link"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, row in enumerate(rows):
            writer.writerow({
                "SL NO.": idx + 1,
                "Title": row.get("Title") or row.get("Paper Link", ""),
                "Authors": row.get("Authors") or "N/A",
                "Published Year": row.get("Published Year") or "N/A",
                "Abstract": row.get("Abstract") or row.get("Paper Link", ""),
                "Paper Link": row.get("Paper Link", "")
            })

    print(f"\n==================================================")
    print(f"[*] REPAIR & CLEANUP SUMMARY:")
    print(f"[*] Total Titles Repaired    : {fixed_titles_count}")
    print(f"[*] Total Abstracts Repaired : {fixed_abstracts_count}")
    print(f"[*] Total Rows in Output     : {len(rows)}")
    print(f"[*] Updated CSV file         : {csv_path}")
    print(f"==================================================\n")

if __name__ == "__main__":
    main()
