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

def format_abstract_text(text):
    if not text:
        return "N/A"
    
    # Strip HTML tags (e.g. <jats:p>, <p>, etc.)
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Slice text starting from 'Abstract' if present
    if "Abstract" in text:
        text = text[text.find("Abstract"):]
    else:
        text = "Abstract\n\n" + text.strip()

    # Strip out UI buttons/navigation text & Keywords / Graphical Abstract
    text = re.sub(r'(?i)\b(?:first_page|settings|Order Article Reprints|Open Access|Download|Browse Figures)\b', '', text)
    text = re.sub(r'(?is)\bKeywords?:.*$', '', text)
    text = re.sub(r'(?is)\bKey\s+words?:.*$', '', text)
    text = re.sub(r'(?is)\bGraphical\s+Abstract.*$', '', text)
    
    # Insert double newlines before common section keywords
    pattern = r'(\b(?:Abstract|Background:?|Objective:?|Methods:?|Results:?|Conclusions?:?))\s*'
    text = re.sub(pattern, r'\n\n\1 ', text)
    
    # Clean whitespace and excess newlines
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text

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

def fetch_crossref_by_doi(doi):
    headers = {"User-Agent": "AcademicResearchPaperScraper/1.0 (mailto:scholar_review@sust.edu)"}
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            msg = data.get("message", {})
            return msg
    except Exception:
        return None

def fetch_crossref_by_title(title):
    headers = {"User-Agent": "AcademicResearchPaperScraper/1.0 (mailto:scholar_review@sust.edu)"}
    clean_t = re.sub(r'[^a-zA-Z0-9\s]', ' ', title)
    query_str = " ".join(clean_t.split()[:12])
    url = f"https://api.crossref.org/works?query.title={urllib.parse.quote(query_str)}&rows=2"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            items = data.get("message", {}).get("items", [])
            if items:
                return items[0]
    except Exception:
        pass
    return None

def fetch_openalex_abstract(doi=None, title=None):
    headers = {"User-Agent": "AcademicResearchPaperScraper/1.0 (mailto:scholar_review@sust.edu)"}
    if doi:
        url = f"https://api.openalex.org/works/https://doi.org/{doi}?mailto=scholar_review@sust.edu"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                inv = data.get("abstract_inverted_index")
                if inv:
                    words = sorted([(idx, w) for w, idxs in inv.items() for idx in idxs])
                    return " ".join([w[1] for w in words]).strip()
        except Exception:
            pass

    if title:
        clean_t = re.sub(r'[^a-zA-Z0-9\s]', ' ', title)
        query_str = " ".join(clean_t.split()[:10])
        url = f"https://api.openalex.org/works?search={urllib.parse.quote(query_str)}&per-page=3&mailto=scholar_review@sust.edu"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                for res in data.get("results", []):
                    inv = res.get("abstract_inverted_index")
                    if inv:
                        words = sorted([(idx, w) for w, idxs in inv.items() for idx in idxs])
                        return " ".join([w[1] for w in words]).strip()
        except Exception:
            pass

    return None

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "scraped_papers.csv")
    input_path = os.path.join(script_dir, "input.txt")

    if not os.path.exists(csv_path):
        print(f"[!] File not found: {csv_path}")
        return

    input_items = []
    if os.path.exists(input_path):
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                input_items = json.load(f)
        except Exception:
            pass

    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        rows = list(csv.DictReader(f))

    if len(rows) > 387:
        rows = rows[-387:]

    print(f"[*] Checking {len(rows)} rows for missing abstracts or errors...")
    
    recovered_count = 0
    checked_count = 0

    for idx, row in enumerate(rows):
        sl = row.get("SL NO.", str(idx + 1))
        link = row.get("Paper Link", "").strip()
        title = row.get("Title", "").strip()
        authors = row.get("Authors", "").strip()
        pub_year = row.get("Published Year", "").strip()
        abstract = row.get("Abstract", "").strip()

        input_item = input_items[idx] if idx < len(input_items) else {}
        orig_title = input_item.get("title", "")
        doc_link = input_item.get("documentLink", "")

        is_missing_abs = (not abstract or abstract == link or abstract in ["N/A", "None"] or len(abstract) < 40)
        is_missing_title = (not title or title == link or title in ["No Title", "Direct URL", "N/A"])

        if is_missing_title and orig_title and orig_title not in ["No Title", "Direct URL"]:
            row["Title"] = orig_title
            title = orig_title

        if (not authors or authors in ["N/A", "None", ""]) and input_item.get("authors") and input_item.get("authors") != "N/A":
            row["Authors"] = input_item.get("authors")
        if (not pub_year or pub_year in ["N/A", "None", ""]) and input_item.get("year") and str(input_item.get("year")) != "N/A":
            row["Published Year"] = str(input_item.get("year"))

        if not is_missing_abs:
            continue

        checked_count += 1
        print(f"[*] Item [{sl}/387] Missing Abstract -> Checking DOIs & Scholarly APIs...")

        doi = extract_doi(link) or extract_doi(doc_link)
        found_abs = None
        cr_msg = None

        if doi:
            cr_msg = fetch_crossref_by_doi(doi)
            time.sleep(0.3)

        search_title = title if (title and title != link) else orig_title
        if not cr_msg and search_title and search_title not in ["No Title", "Direct URL"]:
            cr_msg = fetch_crossref_by_title(search_title)
            if cr_msg and not doi:
                doi = cr_msg.get("DOI")
            time.sleep(0.3)

        if cr_msg:
            raw_cr_abs = cr_msg.get("abstract")
            if raw_cr_abs and len(raw_cr_abs.strip()) > 40:
                found_abs = format_abstract_text(raw_cr_abs)

            if (not row.get("Title") or row.get("Title") == link) and cr_msg.get("title"):
                row["Title"] = cr_msg["title"][0] if isinstance(cr_msg["title"], list) else cr_msg["title"]
            if (not row.get("Authors") or row.get("Authors") in ["N/A", ""]) and cr_msg.get("author"):
                names = []
                for a in cr_msg["author"]:
                    g = a.get("given", "").strip()
                    f_name = a.get("family", "").strip()
                    full = f"{g} {f_name}".strip() if g and f_name else (f_name or g)
                    if full:
                        names.append(full)
                if names:
                    row["Authors"] = ", ".join(names)
            if (not row.get("Published Year") or row.get("Published Year") in ["N/A", ""]) and cr_msg.get("created"):
                dp = cr_msg["created"].get("date-parts")
                if dp and dp[0]:
                    row["Published Year"] = str(dp[0][0])

        if not found_abs:
            oa_text = fetch_openalex_abstract(doi=doi, title=search_title)
            if oa_text and len(oa_text.strip()) > 40:
                found_abs = format_abstract_text(oa_text)
            time.sleep(0.3)

        if found_abs:
            row["Abstract"] = found_abs
            recovered_count += 1
            print(f"  [+] SUCCESS! Recovered abstract for [{sl}]: {row['Title'][:50]}...")
        else:
            row["Abstract"] = link
            print(f"  [-] Could not recover from open databases. Saved link in abstract: {link[:50]}...")

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
    print(f"[*] RECHECK & ENRICHMENT COMPLETED!")
    print(f"[*] Checked Missing Items : {checked_count}")
    print(f"[*] Successfully Recovered: {recovered_count}")
    print(f"[*] Total Rows in CSV     : {len(rows)}")
    print(f"[*] Final CSV updated     : {csv_path}")
    print(f"==================================================\n")

if __name__ == "__main__":
    main()
