"""
Utility to read the crawler status from the status.json file.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

STATUS_FILE_PATH = Path(__file__).parent.parent.parent.parent / "status.json"

def get_crawl_status() -> Dict[str, Any]:
    """Reads the content of the status.json file."""
    if not STATUS_FILE_PATH.exists():
        return {}
    
    try:
        with open(STATUS_FILE_PATH, "r") as f:
            status = json.load(f)
        return status
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not read or parse crawler status file: {e}")
        return {}
