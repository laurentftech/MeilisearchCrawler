# Meilisearch Crawler

This project is a high-performance, asynchronous web crawler designed to populate a Meilisearch instance with content from various websites. It serves as a companion for the [KidSearch](https://github.com/laurentftech/kidsearch) project, a safe search engine for children.

The crawler is configurable via a simple YAML file (`sites.yml`) and supports both HTML pages and JSON APIs as data sources.

## Features

- **Asynchronous & Parallel**: Built with `asyncio` and `aiohttp` for high-speed, concurrent crawling.
- **Multi-site Crawling**: Crawl multiple websites defined in a single `sites.yml` file.
- **Flexible Sources**: Supports both standard HTML websites and JSON APIs.
- **Incremental Indexing**: Uses a local cache to only re-index pages that have changed since the last crawl, saving time and resources.
- **Crawl Resumption**: Automatically resumes crawls that were stopped by page limits, allowing for the progressive indexing of very large sites.
- **Smart Content Extraction**: Uses `trafilatura` for robust, AI-powered main content detection, with fallback to custom heuristics and manual CSS selectors.
- **Language Detection**: Automatically detects the language of HTML pages and allows manual setting for JSON sources, enabling language-specific filtering in search results.
- **Respects `robots.txt`**: Follows standard exclusion protocols, including `Crawl-delay`, to be a good web citizen.
- **Global & Per-Site Exclusions**: Comes with a built-in list of common crawler traps (`/login`, `/cart`, etc.) and allows for site-specific exclusion rules.
- **Advanced CLI**: Powerful command-line options to force re-crawling, target specific sites, clear the cache, and more.
- **Easy Configuration**: All crawl settings are managed through a single `sites.yml` file and a `.env` file for credentials.

## Prerequisites

- Python 3.8+
- A running Meilisearch instance (v1.0 or higher).

## 1. Setting up Meilisearch

This crawler needs a Meilisearch instance to send its data to. The easiest way to get one running is with Docker.

1.  **Install Meilisearch**: Follow the official Meilisearch Quick Start guide. We recommend the Docker method for simplicity.

2.  **Run Meilisearch with a Master Key**:
    ```bash
    docker run -it --rm \
      -p 7700:7700 \
      -e MEILI_MASTER_KEY='a_master_key_that_is_long_and_secure' \
      -v $(pwd)/meili_data:/meili_data \
      ghcr.io/meilisearch/meilisearch:latest
    ```

3.  **Get your URL and API Key**:
    -   **URL**: `http://localhost:7700` if you are running it locally.
    -   **API Key**: Use the `MEILI_MASTER_KEY` you defined. For production, it's recommended to use a more restricted API key.

## 2. Setting up the Crawler

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/laurentftech/MeilisearchCrawler.git
    cd MeilisearchCrawler
    ```

2.  **Create and activate a virtual environment** (Recommended):
    A virtual environment isolates project dependencies and avoids conflicts.
    ```bash
    # Create the environment
    python3 -m venv venv

    # Activate it (on macOS/Linux)
    source venv/bin/activate
    # On Windows, use: venv\Scripts\activate
    ```

3.  **Install dependencies**:
    With the virtual environment active, install the required packages.
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
    Copy the example sites file. This is where you will define which websites the crawler should visit.
    ```bash
    cp sites.yml.example sites.yml
    ```
    You can now edit `sites.yml` to add, remove, or modify the sites you want to index.

## 3. Running the Crawler

Simply run the `crawler.py` script:

```sh
python crawler.py # Runs an incremental crawl on all sites
```

### Command-Line Options

The crawler offers several options to customize its behavior:

-   `--force`: Forces a full re-crawl of all pages, ignoring the cache.
-   `--site "Site Name"`: Crawls only the specified site.
-   `--workers N`: Sets the number of parallel requests (e.g., `--workers 10`).
-   `--verbose`: Enables detailed debug logging.
-   `--clear-cache`: Deletes the cache file before starting.
-   `--stats-only`: Displays cache statistics without running a crawl.

**Example:**

```sh
# Force a re-crawl of "BBC Bitesize" with 10 parallel workers
python crawler.py --force --site "BBC Bitesize" --workers 10
```

The crawler will start, read your `sites.yml` configuration, and begin indexing content into your Meilisearch instance under the `kidsearch` index.

## Running Tests

To run the test suite, first install the development dependencies:

```bash
pip install pytest
```

## Configuration of `sites.yml`

The `sites.yml` file allows you to define a list of sites to crawl. Each site is an object with the following properties:

- `name`: (String) The name of the site, used for filtering in Meilisearch.
- `crawl`: (String) The starting URL for the crawl.
- `type`: (String) The type of content. Can be `html` or `json`.
- `delay`: (Float, optional) Minimum delay in seconds between requests for this site. Overrides `robots.txt` if higher.
- `max_pages`: (Integer) The maximum number of pages to crawl for this site.
- `depth`: (Integer) The maximum depth to follow links from the starting URL. A depth of `1` will only crawl the starting page. A depth of `2` will also crawl the pages linked from it.
- `selector`: (String, optional) For HTML sites, a specific CSS selector (e.g., `.main-article`) to pinpoint the main content area. This overrides automatic detection for tricky layouts.
- `lang`: (String, optional) For JSON sources, specifies the language of the content (e.g., "en", "fr"). For HTML, it's auto-detected.
- `exclude`: (List of strings) A list of URL patterns to completely ignore. Any URL matching one of these patterns will not be visited. This applies to both HTML pages and items from JSON sources.
- `no_index`: (List of strings) A list of URL patterns to visit for link discovery but not to index. This is useful for sitemap pages or category indexes whose content is not valuable for search results.

### JSON Type Specific Configuration

If `type` is `json`, you must also provide a `json` object with the following mapping:

- `root`: The key in the JSON response that contains the list of items.
- `title`: The key for the item's title.
- `url`: The key for the item's URL.
-   **URL Templating**: You can construct URLs using values from the JSON object. Use `{{key_name}}` to substitute a value. For example: `"https://example.com/books/{{id}}"`.
- `content`: A comma-separated list of keys for the content. You can use `[]` to access all items in a list (e.g., `authors[].name`).
- `image`: The key for the item's main image URL.
-   **Image URL Templating**: This also supports templating like the `url` field. For example: `"https://covers.example.com/{{cover_id}}.jpg"`.