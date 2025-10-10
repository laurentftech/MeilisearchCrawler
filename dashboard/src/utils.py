import json
import os
import re
import yaml
from datetime import datetime

from .config import (
    STATUS_FILE,
    SITES_CONFIG_FILE,
    CACHE_FILE,
    LOG_FILE,
    HISTORY_FILE
)

def load_json(file_path):
    """Loads a JSON file."""
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

def load_status():
    """Loads the crawler status from status.json."""
    return load_json(STATUS_FILE)

def load_sites_config():
    """Loads the site configuration from sites.yml."""
    if not os.path.exists(SITES_CONFIG_FILE):
        return None
    try:
        with open(SITES_CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, IOError) as e:
        print(f"Error loading YAML file: {e}")
        return None

def save_sites_config(config):
    """Saves the given configuration to sites.yml."""
    try:
        with open(SITES_CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        return True
    except IOError as e:
        print(f"Error saving YAML file: {e}")
        return False

def load_cache_stats():
    """Loads statistics from the crawler cache file."""
    cache = load_json(CACHE_FILE)
    if not cache:
        return None
    return {
        'total_urls': len(cache),
        'sites': len(set(url.split('/')[2] for url in cache.keys() if '://' in url))
    }

def parse_logs_for_errors(n=100):
    """Extracts the most recent errors from the log file."""
    if not os.path.exists(LOG_FILE):
        return []

    errors = []
    try:
        with open(LOG_FILE, "r", encoding='utf-8') as f:
            lines = f.readlines()[-n:]

        for line in lines:
            if 'ERROR' in line or 'Exception' in line:
                match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                timestamp = match.group(1) if match else "N/A"
                errors.append({'timestamp': timestamp, 'message': line.strip()})
    except IOError:
        pass
    return errors

def save_crawl_history(status):
    """Saves the latest crawl status to the history file."""
    history = load_json(HISTORY_FILE) or []

    history.append({
        'timestamp': datetime.now().isoformat(),
        'pages_indexed': status.get('pages_indexed', 0),
        'sites_crawled': status.get('sites_crawled', 0),
        'errors': status.get('errors', 0),
        'duration': status.get('last_crawl_duration_sec', 0)
    })

    # Keep only the last 100 entries
    history = history[-100:]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except IOError:
        pass

def load_crawl_history():
    """Loads the crawl history."""
    return load_json(HISTORY_FILE) or []
