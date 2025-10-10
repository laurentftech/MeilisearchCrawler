import os
from dotenv import load_dotenv

# Determine BASE_DIR from the location of this config file.
# This file is in dashboard/src/, so we go up three levels to get to the project root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
LOG_FILE = os.path.join(DATA_DIR, "logs", "crawler.log")
CACHE_FILE = os.path.join(DATA_DIR, "crawler_cache.json")
PID_FILE = os.path.join(DATA_DIR, "crawler.pid")
CRAWLER_SCRIPT = os.path.join(BASE_DIR, "crawler.py")
SITES_CONFIG_FILE = os.path.join(CONFIG_DIR, "sites.yml")
HISTORY_FILE = os.path.join(DATA_DIR, "crawl_history.json")

# Load environment variables from .env file in the project root
load_dotenv(os.path.join(BASE_DIR, ".env"))

MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
