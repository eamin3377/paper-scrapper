# Paper Scrapper - Lite Selenium Browser

A lightweight, resource-optimized Selenium browser script built in Python to open URLs quickly with minimal CPU, RAM, and network consumption.

## Features

- ⚡ **Headless Mode**: Runs Chrome in `--headless=new` mode without launching GUI windows.
- 🖼️ **Disabled Images & Notifications**: Saves bandwidth and loads pages faster by blocking image fetching and popup notifications.
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

Run the script by passing any target URL as an argument:

```bash
python p.py https://example.com
```

If no URL is provided, it defaults to `https://example.com`.

### Python Import Usage

You can also import `open_url` or `create_lite_driver` into your own scripts:

```python
from p import open_url

result = open_url("https://news.ycombinator.com", headless=True, disable_images=True)
print(result["title"])
```
