# Paper Scrapper - Lite Selenium Browser

A lightweight, resource-optimized Selenium browser script built in Python to open URLs and process paper links from JSON files like `paper.txt`.

## Features

- 📄 **Automatic JSON Link Extraction**: Reads `paper.txt` (or any raw JSON file) and extracts `"link": "https://..."` targets automatically.
- 👁️ **Visible Inspection Mode (Default)**: Opens a visible Chrome browser window with a pause so you can watch each paper link load and observe the contents live.
- ⚡ **Headless Mode Support**: Pass `--headless` to run silently in the background.
- 🚀 **Eager Page Loading**: Configured with `eager` page load strategy for fast DOM ready loading.
- 🛠️ **Automatic Driver Management**: Automatically downloads and manages `chromedriver` using `webdriver-manager`.

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/eamin3377/paper-scrapper.git
   cd paper-scrapper
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### 1. Process Links from `paper.txt` (Default)
Simply run the script with no arguments (or pass `paper.txt`):

```bash
python p.py
```

Or specify `paper.txt` explicitly:

```bash
python p.py paper.txt
```

### 2. Open a Single Direct URL
Pass any URL directly:

```bash
python p.py https://link.springer.com/article/10.1186/s12911-025-03246-7
```

### 3. Headless Execution
Add `--headless` to run without launching a browser window:

```bash
python p.py paper.txt --headless
```

## JSON File Format (`paper.txt`)

The script expects a JSON array of paper objects containing `"link"` fields, for example:

```json
[
  {
    "title": "From dry eye to depression: a machine learning-based framework",
    "link": "https://link.springer.com/article/10.1186/s12911-025-03246-7"
  }
]
```
