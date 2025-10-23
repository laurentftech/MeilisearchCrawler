
import httpx
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class WikiClient:
    """
    A client for fetching search results from a MediaWiki API (like Wikipedia or Vikidia).
    """
    def __init__(self, api_url: str):
        """
        Initializes the WikiClient.

        Args:
            api_url: The base URL of the MediaWiki API (e.g., "https://en.wikipedia.org/w/api.php").
        """
        self.api_url = api_url
        self.client = httpx.AsyncClient(base_url=self.api_url)

    async def search(self, query: str, lang: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Performs a search on the MediaWiki API.

        Args:
            query: The search query.
            lang: The language code for the search (e.g., "en", "fr").
            limit: The maximum number of results to return.

        Returns:
            A list of search result dictionaries.
        """
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "srprop": "snippet|titlesnippet",
            "origin": "*",
        }
        try:
            response = await self.client.get("", params=params)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("query", {}).get("search", []):
                results.append({
                    "title": item["title"],
                    "url": f"https://{lang}.vikidia.org/wiki/{item['title'].replace(' ', '_')}",
                    "snippet": item["snippet"],
                })
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error while searching wiki: {e}")
            return []
        except Exception as e:
            logger.error(f"Error searching wiki: {e}")
            return []

