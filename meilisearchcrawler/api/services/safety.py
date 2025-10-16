"""
Safety filtering service for child-safe search results.
Filters inappropriate domains, keywords, and content.
"""

import logging
import re
from typing import List, Set, Dict, Any
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..models import SearchResult

logger = logging.getLogger(__name__)


class SafetyFilter:
    """
    Safety filter for KidSearch.
    Filters out inappropriate content based on:
    - Domain blacklist/whitelist
    - Keyword matching
    - Content patterns
    """

    def __init__(self, config_path: str = "config/safety_filters.yml"):
        """
        Initialize safety filter.

        Args:
            config_path: Path to safety filters configuration
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = {}

        self.blocked_domains: Set[str] = set()
        self.allowed_domains: Set[str] = set()
        self.blocked_keywords: List[str] = []
        self.blocked_patterns: List[re.Pattern] = []

        self.load_config()

    def load_config(self):
        """Load safety filters configuration from YAML."""
        config_file = Path(self.config_path)

        if not config_file.exists():
            logger.warning(
                f"Safety filter config not found: {self.config_path}, "
                "using defaults"
            )
            self._load_defaults()
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}

            # Load blocked domains
            blocked_domains = self.config.get("blocked_domains") or []
            self.blocked_domains = set(
                d.lower() for d in blocked_domains if d
            )

            # Load allowed domains (whitelist mode)
            allowed_domains = self.config.get("allowed_domains") or []
            self.allowed_domains = set(
                d.lower() for d in allowed_domains if d
            )

            # Load blocked keywords
            blocked_keywords = self.config.get("blocked_keywords") or []
            self.blocked_keywords = [
                kw.lower() for kw in blocked_keywords if kw
            ]

            # Compile regex patterns
            patterns = self.config.get("blocked_patterns") or []
            self.blocked_patterns = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns if pattern
            ]

            logger.info(
                f"Safety filter loaded: {len(self.blocked_domains)} blocked domains, "
                f"{len(self.allowed_domains)} allowed domains, "
                f"{len(self.blocked_keywords)} blocked keywords"
            )

        except Exception as e:
            logger.error(f"Failed to load safety config: {e}", exc_info=True)
            self._load_defaults()

    def _load_defaults(self):
        """Load default safety filters."""
        # Minimal default filters
        self.blocked_domains = set()
        self.allowed_domains = set()
        self.blocked_keywords = []
        self.blocked_patterns = []

    def filter_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """
        Filter search results for child safety.

        Args:
            results: Search results to filter

        Returns:
            Filtered results (safe for children)
        """

        filtered = []
        blocked_count = 0

        for result in results:
            if self.is_safe(result):
                filtered.append(result)
            else:
                blocked_count += 1
                logger.debug(
                    f"Result blocked by safety filter: {result.url} "
                    f"(title: {result.title[:50]}...)"
                )

        if blocked_count > 0:
            logger.info(f"Safety filter blocked {blocked_count} results")

        return filtered

    def is_safe(self, result: SearchResult) -> bool:
        """
        Check if a search result is safe for children.

        Args:
            result: Search result to check

        Returns:
            True if safe, False otherwise
        """

        # Check domain whitelist (if configured)
        if self.allowed_domains:
            domain = self._extract_domain(result.url)
            if domain not in self.allowed_domains:
                logger.debug(f"Domain not in whitelist: {domain}")
                return False

        # Check domain blacklist
        domain = self._extract_domain(result.url)
        if domain in self.blocked_domains:
            logger.debug(f"Domain blocked: {domain}")
            return False

        # Check URL against blocked keywords
        url_lower = str(result.url).lower()
        for keyword in self.blocked_keywords:
            if keyword in url_lower:
                logger.debug(f"URL contains blocked keyword '{keyword}': {result.url}")
                return False

        # Check title against blocked keywords
        title_lower = result.title.lower()
        for keyword in self.blocked_keywords:
            if keyword in title_lower:
                logger.debug(f"Title contains blocked keyword '{keyword}': {result.title}")
                return False

        # Check excerpt/content against blocked keywords
        text_lower = (result.excerpt or "").lower()
        if result.content:
            text_lower += " " + result.content.lower()

        for keyword in self.blocked_keywords:
            if keyword in text_lower:
                logger.debug(f"Content contains blocked keyword '{keyword}'")
                return False

        # Check against regex patterns
        combined_text = f"{result.title} {result.excerpt or ''} {result.content or ''}"
        for pattern in self.blocked_patterns:
            if pattern.search(combined_text):
                logger.debug(f"Content matches blocked pattern: {pattern.pattern}")
                return False

        # Passed all checks
        return True

    def _extract_domain(self, url: str) -> str:
        """
        Extract domain from URL.

        Args:
            url: URL to parse

        Returns:
            Domain (lowercase, without www.)
        """
        parsed = urlparse(str(url))
        domain = parsed.netloc.lower()

        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]

        return domain

    def add_blocked_domain(self, domain: str):
        """
        Add a domain to the blocklist.

        Args:
            domain: Domain to block
        """
        domain = domain.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        self.blocked_domains.add(domain)
        logger.info(f"Domain added to blocklist: {domain}")

    def add_blocked_keyword(self, keyword: str):
        """
        Add a keyword to the blocklist.

        Args:
            keyword: Keyword to block
        """
        keyword = keyword.lower()
        if keyword not in self.blocked_keywords:
            self.blocked_keywords.append(keyword)
            logger.info(f"Keyword added to blocklist: {keyword}")

    def save_config(self):
        """Save current filter configuration to YAML."""
        config_file = Path(self.config_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        config = {
            "blocked_domains": sorted(list(self.blocked_domains)),
            "allowed_domains": sorted(list(self.allowed_domains)),
            "blocked_keywords": self.blocked_keywords,
            "blocked_patterns": [p.pattern for p in self.blocked_patterns],
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Safety filter configuration saved to {config_file}")


# TODO: Implement ML-based content classification
# - Train a classifier on kid-safe vs unsafe content
# - Use it as an additional safety layer
# - Periodically retrain based on user feedback

# TODO: Implement age-based filtering
# - Different safety levels for different age groups
# - Configurable strictness levels
