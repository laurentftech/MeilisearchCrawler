from abc import ABC, abstractmethod
from typing import List, Optional
import logging
import os
import requests
from cachetools import LRUCache
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.embedding_dim = None  # To be set by subclasses

    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts"""
        pass

    @abstractmethod
    def get_embedding_dim(self) -> int:
        """Return the dimension of the embeddings"""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the generic name of the provider (e.g., 'gemini')."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the specific name of the model (e.g., 'intfloat/multilingual-e5-base')."""
        pass


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Provider using Google Gemini for embeddings"""

    def __init__(self, api_key: str, model_name: str = "text-embedding-004"):
        super().__init__(model_name)
        self.embedding_dim = 768

        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            logger.info(f"✓ Gemini initialized with model {model_name}")
        except ImportError:
            raise ImportError("'google-genai' package is required for Gemini. Install with: pip install google-genai")
        except Exception as e:
            raise RuntimeError(f"Could not initialize Gemini: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings with the Gemini API"""
        try:
            result = self.client.models.embed_content(
                model=f"models/{self.model_name}",
                contents=texts
            )
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            logger.error(f"❌ Error during encoding with Gemini: {e}")
            return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return self.embedding_dim

    def get_provider_name(self) -> str:
        return "gemini"

    def get_model_name(self) -> str:
        return self.model_name


class HuggingFaceInferenceAPIEmbeddingProvider(EmbeddingProvider):
    """Provider using a Hugging Face Inference API (like text-embeddings-inference)"""

    MODEL_DIMENSIONS = {
        'intfloat/multilingual-e5-small': 384,
        'intfloat/multilingual-e5-base': 768,
        'Snowflake/snowflake-arctic-embed-xs': 384,
        'Snowflake/snowflake-arctic-embed-s': 384,
        'Snowflake/snowflake-arctic-embed-m': 768,
        'Snowflake/snowflake-arctic-embed-l': 1024,
    }

    def __init__(self, model_name: str = "intfloat/multilingual-e5-base", api_url: str = "http://localhost:8080/embed"):
        super().__init__(model_name)
        self.api_url = api_url
        self.embedding_dim = self.MODEL_DIMENSIONS.get(model_name, 768)
        self.batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
        self.timeout = int(os.getenv("EMBEDDING_TIMEOUT", "10"))
        self._embedding_cache = LRUCache(maxsize=int(os.getenv("EMBEDDING_CACHE_SIZE", "2048")))

        try:
            import requests
        except ImportError:
            raise ImportError("'requests' package is required. Install with: pip install requests")

        logger.info(f"✓ HuggingFace Inference API provider initialized for model {model_name} on {api_url}")
        self._verify_api_connection()

    def _verify_api_connection(self):
        try:
            base_url = self.api_url.rsplit('/', 1)[0]
            response = requests.get(f"{base_url}/info", timeout=5)
            response.raise_for_status()
            info = response.json()
            logger.info(f"✓ Inference API connection successful: version {info.get('version')}, model {info.get('model_id')}")
            
            if self.model_name != info.get('model_id'):
                logger.warning(f"Configured model ({self.model_name}) differs from API model ({info.get('model_id')}). Using API model.")
                self.model_name = info.get('model_id')
                self.embedding_dim = self.MODEL_DIMENSIONS.get(self.model_name, self.embedding_dim)

            test_response = requests.post(
                self.api_url,
                json={"inputs": ["test"], "normalize": True, "truncate": True},
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            test_response.raise_for_status()
            test_embeddings = test_response.json()
            if isinstance(test_embeddings, list) and len(test_embeddings) > 0 and isinstance(test_embeddings[0], list):
                detected_dim = len(test_embeddings[0])
                if detected_dim != self.embedding_dim:
                    logger.warning(f"Configured dimension ({self.embedding_dim}D) differs from detected ({detected_dim}D). Using detected dimension.")
                    self.embedding_dim = detected_dim
                else:
                    logger.info(f"✓ Dimension verified: {self.embedding_dim}D")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Could not connect to Hugging Face Inference API at {self.api_url}: {e}")
        except Exception as e:
            logger.warning(f"Could not verify inference API info: {e}")

    def encode(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings with batching, caching, and error handling."""
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_texts: List[str] = []
        uncached_indices: List[int] = []

        for i, text in enumerate(texts):
            if text in self._embedding_cache:
                results[i] = self._embedding_cache[text]
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        if not uncached_texts:
            logger.debug(f"All {len(texts)} embeddings retrieved from cache.")
            return results

        logger.debug(f"Requesting {len(uncached_texts)} embeddings in batches of {self.batch_size}.")

        for i in range(0, len(uncached_texts), self.batch_size):
            batch_texts = uncached_texts[i:i + self.batch_size]
            batch_indices = uncached_indices[i:i + self.batch_size]

            try:
                response = requests.post(
                    self.api_url,
                    json={"inputs": batch_texts, "normalize": True, "truncate": True},
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout
                )
                response.raise_for_status()
                embeddings = response.json()

                for j, embedding in enumerate(embeddings):
                    original_index = batch_indices[j]
                    original_text = batch_texts[j]
                    results[original_index] = embedding
                    self._embedding_cache[original_text] = embedding

            except requests.Timeout:
                logger.warning(f"Timeout ({self.timeout}s) for embedding batch of {len(batch_texts)} texts.")
            except Exception as e:
                logger.error(f"Hugging Face API error for batch: {e}")
        
        return results

    def get_embedding_dim(self) -> int:
        return self.embedding_dim

    def get_provider_name(self) -> str:
        return "huggingface"

    def get_model_name(self) -> str:
        return self.model_name


class NoEmbeddingProvider(EmbeddingProvider):
    """Empty provider (no embeddings)"""

    def __init__(self):
        super().__init__("none")
        self.embedding_dim = 0

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Return empty embeddings"""
        return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return 0

    def get_provider_name(self) -> str:
        return "none"

    def get_model_name(self) -> str:
        return "none"


def create_embedding_provider(provider_name: Optional[str] = None) -> EmbeddingProvider:
    """
    Factory to create an embedding provider based on configuration.

    Args:
        provider_name: Name of the provider ('gemini', 'huggingface', 'none')
                      If None, reads from EMBEDDING_PROVIDER in .env

    Returns:
        Instance of the embedding provider
    """
    if provider_name is None:
        provider_name = os.getenv('EMBEDDING_PROVIDER', 'none').lower()

    provider_name = provider_name.lower().strip()

    logger.info(f"🔧 Configuring embedding provider: {provider_name}")

    if provider_name == 'gemini':
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.warning("⚠️ GEMINI_API_KEY not found - embeddings disabled")
            return NoEmbeddingProvider()

        try:
            return GeminiEmbeddingProvider(api_key=api_key)
        except Exception as e:
            logger.error(f"❌ Gemini initialization failed: {e}")
            logger.warning("   Switching to no-embedding mode")
            return NoEmbeddingProvider()

    elif provider_name == 'huggingface':
        model_name = os.getenv('HUGGINGFACE_MODEL', 'intfloat/multilingual-e5-small')
        api_url = os.getenv('HUGGINGFACE_API_URL', 'http://localhost:8081/embed')

        try:
            return HuggingFaceInferenceAPIEmbeddingProvider(model_name=model_name, api_url=api_url)
        except Exception as e:
            logger.error(f"❌ HuggingFace Inference API initialization failed: {e}")
            logger.warning("   Switching to no-embedding mode")
            return NoEmbeddingProvider()

    elif provider_name == 'none':
        logger.info("ℹ️ Embeddings disabled")
        return NoEmbeddingProvider()

    else:
        logger.warning(f"⚠️ Unknown provider '{provider_name}' - embeddings disabled")
        logger.info("   Available providers: gemini, huggingface, none")
        return NoEmbeddingProvider()
