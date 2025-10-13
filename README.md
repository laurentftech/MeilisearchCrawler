# Meilisearch Crawler

This project is a high-performance, asynchronous web crawler designed to populate a Meilisearch instance with content from various websites. It serves as a companion for the [KidSearch](https://github.com/laurentftech/kidsearch) project, a safe search engine for children.

The crawler is configurable via a simple YAML file (`sites.yml`) and supports both HTML pages and JSON APIs as data sources.

## Features

- **Asynchronous & Parallel**: Built with `asyncio` and `aiohttp` for high-speed, concurrent crawling.
- **Interactive Dashboard**: A Streamlit-based web UI to monitor, control, and configure the crawler in real-time.
- **Multi-site Crawling**: Crawl multiple websites defined in a single `sites.yml` file.
- **Flexible Sources**: Supports both standard HTML websites and JSON APIs.
- **Incremental Indexing**: Uses a local cache to only re-index pages that have changed since the last crawl.
- **Crawl Resumption**: Automatically resumes crawls that were stopped by page limits.
- **Smart Content Extraction**: Uses `trafilatura` for robust main content detection.
- **Language Detection**: Automatically detects the language of pages.
- **Respects `robots.txt`**: Follows standard exclusion protocols.
- **Global & Per-Site Exclusions**: Define global and site-specific URL patterns to ignore.
- **Advanced CLI**: Powerful command-line options for fine-grained control.

![screenshot_dashboard.png](media/screenshot_dashboard_en.png)

## Prerequisites

- Python 3.8+
- A running Meilisearch instance (v1.0 or higher).

## 1. Setting up Meilisearch

This crawler needs a Meilisearch instance to send its data to. The easiest way to get one running is with Docker.

1.  **Install Meilisearch**: Follow the official Meilisearch Quick Start guide.
2.  **Run Meilisearch with a Master Key**:
    ```bash
    docker run -it --rm \
      -p 7700:7700 \
      -e MEILI_MASTER_KEY='a_master_key_that_is_long_and_secure' \
      -e GEMINI_API_KEY='your_gemini_api_key' \
      -v $(pwd)/meili_data:/meili_data \
      ghcr.io/meilisearch/meilisearch:latest
    ```
3.  **Get your URL and API Key**:
    -   **URL**: `http://localhost:7700`
    -   **API Key**: The `MEILI_MASTER_KEY` you defined.

## 2. Setting up the Crawler

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/laurentftech/MeilisearchCrawler.git
    cd MeilisearchCrawler
    ```

2.  **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables**:
    Copy the example file and edit it with your Meilisearch credentials.
    ```bash
    cp .env.example .env
    ```
    Now, open `.env` and fill in your `MEILI_URL` and `MEILI_KEY`.

5.  **Configure sites to crawl**:
    Copy the example sites file.
    ```bash
    cp config/sites.yml.example config/sites.yml
    ```
    You can now edit `config/sites.yml` to add the sites you want to index.

## 3. Running the Crawler

You can run the crawler via the command line or the interactive dashboard.

### Command-Line Interface

Simply run the `crawler.py` script:

```sh
python crawler.py # Runs an incremental crawl on all sites
```

**Common Options:**

-   `--force`: Forces a full re-crawl of all pages, ignoring the cache.
-   `--site "Site Name"`: Crawls only the specified site.
-   `--workers N`: Sets the number of parallel requests (e.g., `--workers 10`).
-   `--stats-only`: Displays cache statistics without running a crawl.

**Example:**
```sh
# Force a re-crawl of "BBC Bitesize" with 10 parallel workers
python crawler.py --force --site "BBC Bitesize" --workers 10
```

### Interactive Dashboard

The project includes a web-based dashboard to monitor and control the crawler in real-time.

**How to Run:**

1.  From the project root, run the following command:
    ```bash
    streamlit run dashboard/dashboard.py
    ```
2.  Open your web browser to the local URL provided by Streamlit (usually `http://localhost:8501`).

**Features:**

-   **🏠 Overview**: A real-time summary of the current crawl, including pages indexed, sites crawled, errors, and progress charts.
-   **🔧 Controls**: Start or stop the crawler, select a specific site, force a re-crawl, and clear the cache.
-   **🔍 Search**: A live search interface to test queries directly against your Meilisearch index.
-   **📊 Statistics**: Detailed statistics about your Meilisearch index, including document distribution by site and field distribution.
-   **🌳 Page Tree**: An interactive visualization of your site's structure, showing the freshness of indexed pages and pages pending crawl.
-   **⚙️ Configuration**: An interactive editor to view and modify the `sites.yml` configuration file.
-   **🪵 Logs**: A live view of the crawler's log file.

## 4. Configuration of `sites.yml`

The `config/sites.yml` file allows you to define a list of sites to crawl. Each site is an object with the following properties:

- `name`: (String) The name of the site, used for filtering in Meilisearch.
- `crawl`: (String) The starting URL for the crawl.
- `type`: (String) The type of content. Can be `html` or `json`.
- `delay`: (Float, optional) Minimum delay in seconds between requests for this site.
- `max_pages`: (Integer) The maximum number of pages to crawl. Set to `0` or omit for no limit.
- `depth`: (Integer) The maximum depth to follow links from the starting URL.
- `selector`: (String, optional) For HTML sites, a specific CSS selector (e.g., `.main-article`) to pinpoint the main content area.
- `lang`: (String, optional) For JSON sources, specifies the language of the content (e.g., "en", "fr").
- `exclude`: (List of strings) A list of URL patterns to completely ignore.
- `no_index`: (List of strings) A list of URL patterns to visit for link discovery but not to index.

### JSON Type Specific Configuration

If `type` is `json`, you must also provide a `json` object with the following mapping:

- `root`: The key in the JSON response that contains the list of items.
- `title`: The key for the item's title.
- `url`: The key for the item's URL. You can use `{{key_name}}` to substitute a value.
- `content`: A comma-separated list of keys for the content.
- `image`: The key for the item's main image URL.

## 5. Running Tests

To run the test suite, first install the development dependencies:

```bash
pip install pytest
```

Then, run the tests:
```bash
pytest
```
