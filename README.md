# Paper Scrapper - Lite Selenium Browser

A lightweight, resource-optimized Selenium browser script built in Python to open URLs quickly.

## Features

- 👁️ **Visible Inspection Mode (Default)**: Opens a visible Chrome browser window so you can watch the page loading and inspect elements live.
- ⚡ **Headless Mode Support**: Pass `--headless` if you want to run silently in the background.
- 🖼️ **Optional Image & Notification Blocking**: Saves bandwidth and loads pages faster.
- 🚀 **Eager Page Loading**: Configured with `eager` page load strategy to start processing as soon as the DOM is ready.
- 🛠️ **Automatic Driver Management**: Automatically downloads and manages `chromedriver` using `webdriver-manager`.

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/eamin3377/paper-scrapper.git
   cd paper-scrapper
   ```

2. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/macOS
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### 1. Visible Mode (Default)
Run the script to open a visible Chrome window for visual inspection:

```bash
python p.py https://example.com
```

### 2. Headless Mode
Add `--headless` to run silently in the background:

```bash
python p.py https://example.com --headless
```

### Python Import Usage

You can also import `open_url` or `create_lite_driver` into your own scripts:

```python
from p import open_url

# Visible window with 5-second pause to inspect page
result = open_url("https://news.ycombinator.com", headless=False, wait_time=5)
print(result["title"])
```
