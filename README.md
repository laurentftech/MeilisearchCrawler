# Meilisearch Crawler for KidSearch

This project is a flexible web crawler designed to populate a Meilisearch instance with content from various websites. It serves as a companion for the [KidSearch](https://github.com/laurentftech/kidsearch) project, a safe search engine for children.

The crawler is configurable via a simple YAML file (`sites.yml`) and supports both HTML pages and JSON APIs as data sources.

## Features

- **Multi-site Crawling**: Crawl several websites defined in `sites.yml`.
- **Flexible Sources**: Supports both standard HTML websites and JSON APIs.
- **Incremental Indexing**: Uses a local cache to only re-index pages that have changed since the last crawl, saving time and resources.
- **Smart Content Extraction**: Intelligently attempts to find and clean the main content of a webpage, removing headers, footers, and sidebars.
- **Easy Configuration**: All settings are managed through a `sites.yml` file and a `.env` file for credentials.

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

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment variables**:
    Copy the example file and edit it with your Meilisearch credentials.
    ```bash
    cp .env.example .env
    ```
    Now, open `.env` and fill in your `MEILI_URL` and `MEILI_KEY`.

4.  **Configure sites to crawl**:
    Copy the example sites file. This is where you will define which websites the crawler should visit.
    ```bash
    cp sites.yml.example sites.yml
    ```
    You can now edit `sites.yml` to add, remove, or modify the sites you want to index.

## 3. Running the Crawler

Simply run the `crawler.py` script:

```bash
python crawler.py
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
- `max_pages`: (Integer) The maximum number of pages to crawl for this site.
- `depth`: (Integer) The maximum depth to follow links from the starting URL. A depth of `1` will only crawl the starting page. A depth of `2` will also crawl the pages linked from it.
- `exclude`: (List of strings) A list of URL patterns to exclude from the crawl. Any URL containing one of these strings will be ignored.

### JSON Type Specific Configuration

If `type` is `json`, you must also provide a `json` object with the following mapping:

- `root`: The key in the JSON response that contains the list of items.
- `id`: The key for the unique identifier of each item.
- `title`: The key for the item's title.
- `url`: The key for the item's URL.
-   **URL Templating**: You can construct URLs using values from the JSON object. Use `{{key_name}}` to substitute a value. For example: `"https://example.com/books/{{id}}"`.
- `content`: A comma-separated list of keys for the content. You can use `[]` to access all items in a list (e.g., `authors[].name`).
- `image`: The key for the item's main image URL.
-   **Image URL Templating**: This also supports templating like the `url` field. For example: `"https://covers.example.com/{{cover_id}}.jpg"`.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

MIT