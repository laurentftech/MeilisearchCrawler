import streamlit as st
import os
import yaml
import re
import json
from meilisearch_python_sdk import Client
from .config import MEILI_URL, MEILI_KEY, SITES_CONFIG_FILE, LOG_FILE, STATUS_FILE, HISTORY_FILE

@st.cache_resource
def get_meili_client():
    if MEILI_URL and MEILI_KEY:
        return Client(MEILI_URL, MEILI_KEY)
    return None

def load_sites_config():
    try:
        with open(SITES_CONFIG_FILE, "r", encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return None

def save_sites_config(config_data):
    try:
        with open(SITES_CONFIG_FILE, "w", encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde de la configuration des sites: {e}")
        return False

def load_status():
    try:
        with open(STATUS_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def load_crawl_history():
    try:
        with open(HISTORY_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_crawl_history(status, max_entries=100):
    history = load_crawl_history()
    new_entry = {
        "timestamp": status.get("timestamp"),
        "pages_indexed": status.get("pages_indexed", 0),
        "errors": status.get("errors", 0),
        "duration": status.get("last_crawl_duration_sec", 0)
    }
    if history and history[-1].get("timestamp") == new_entry["timestamp"]:
        return
    history.append(new_entry)
    if len(history) > max_entries:
        history = history[-max_entries:]
    try:
        with open(HISTORY_FILE, "w", encoding='utf-8') as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        st.error(f"Failed to save crawl history: {e}")

def load_cache_stats():
    # This function is deprecated as cache is now in SQLite
    return {"total_urls": 0, "sites": 0}

def parse_logs_for_errors(limit=100):
    errors = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if 'ERROR' in line:
                    match = re.search(r'\[(.*?)\] \[ERROR\] \[.*?\] (.*)', line)
                    if match:
                        errors.append({"timestamp": match.group(1), "message": match.group(2)})
    except FileNotFoundError:
        pass
    return errors[-limit:]
