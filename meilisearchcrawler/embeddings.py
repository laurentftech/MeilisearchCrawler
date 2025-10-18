"""
Module pour la génération d'embeddings avec différents providers
Supporte: Google Gemini, Snowflake Arctic Embed
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import logging
import os

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Interface abstraite pour les providers d'embeddings"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.embedding_dim = None  # Sera défini par les sous-classes

    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        """Génère des embeddings pour une liste de textes"""
        pass

    @abstractmethod
    def get_embedding_dim(self) -> int:
        """Retourne la dimension des embeddings"""
        pass


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Provider utilisant Google Gemini pour les embeddings"""

    def __init__(self, api_key: str, model_name: str = "text-embedding-004"):
        super().__init__(model_name)
        self.embedding_dim = 768

        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            logger.info(f"✓ Gemini initialisé avec le modèle {model_name}")
        except ImportError:
            raise ImportError("Le package 'google-genai' est requis pour Gemini. Installez-le avec: pip install google-genai")
        except Exception as e:
            raise RuntimeError(f"Impossible d'initialiser Gemini: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Génère des embeddings avec Gemini"""
        try:
            result = self.client.models.embed_content(
                model=self.model_name,
                contents=texts
            )
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            if "quota" in str(e).lower():
                logger.error(f"🛑 Quota Gemini dépassé: {e}")
            else:
                logger.error(f"❌ Erreur API Gemini: {e}")
            return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return self.embedding_dim


class SnowflakeEmbeddingProvider(EmbeddingProvider):
    """Provider utilisant Snowflake Arctic Embed (local)"""

    # Dimensions selon les modèles Snowflake
    MODEL_DIMENSIONS = {
        'Snowflake/snowflake-arctic-embed-xs': 384,  # 22M params
        'Snowflake/snowflake-arctic-embed-s': 384,   # 33M params
        'Snowflake/snowflake-arctic-embed-m': 768,   # 110M params
        'Snowflake/snowflake-arctic-embed-l': 1024,  # 335M params
    }

    def __init__(self, model_name: str = "Snowflake/snowflake-arctic-embed-s"):
        super().__init__(model_name)
        self.embedding_dim = self.MODEL_DIMENSIONS.get(model_name, 384)

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"📦 Chargement du modèle Snowflake: {model_name}...")
            self.model = SentenceTransformer(model_name, trust_remote_code=True)
            logger.info(f"✓ Snowflake Arctic initialisé ({self.embedding_dim}D)")
        except ImportError:
            raise ImportError("Le package 'sentence-transformers' est requis pour Snowflake. Installez-le avec: pip install sentence-transformers")
        except Exception as e:
            raise RuntimeError(f"Impossible de charger le modèle Snowflake {model_name}: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Génère des embeddings avec Snowflake Arctic"""
        try:
            # Snowflake Arctic utilise des queries et documents
            # Pour la recherche, on encode tout comme des queries
            embeddings = self.model.encode(
                texts,
                prompt_name="query",  # Utiliser le prompt optimisé pour les queries
                show_progress_bar=False,
                convert_to_numpy=True
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"❌ Erreur Snowflake encoding: {e}")
            return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return self.embedding_dim


class NoEmbeddingProvider(EmbeddingProvider):
    """Provider vide (pas d'embeddings)"""

    def __init__(self):
        super().__init__("none")
        self.embedding_dim = 0

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Retourne des embeddings vides"""
        return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return 0


def create_embedding_provider(provider_name: Optional[str] = None) -> EmbeddingProvider:
    """
    Factory pour créer un provider d'embeddings basé sur la configuration

    Args:
        provider_name: Nom du provider ('gemini', 'snowflake', 'none')
                      Si None, lit depuis EMBEDDING_PROVIDER dans .env

    Returns:
        Instance du provider d'embeddings
    """
    if provider_name is None:
        provider_name = os.getenv('EMBEDDING_PROVIDER', 'none').lower()

    provider_name = provider_name.lower().strip()

    logger.info(f"🔧 Configuration du provider d'embeddings: {provider_name}")

    if provider_name == 'gemini':
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.warning("⚠️  GEMINI_API_KEY non trouvée - embeddings désactivés")
            return NoEmbeddingProvider()

        try:
            return GeminiEmbeddingProvider(api_key=api_key)
        except Exception as e:
            logger.error(f"❌ Échec initialisation Gemini: {e}")
            logger.warning("   Basculement vers mode sans embeddings")
            return NoEmbeddingProvider()

    elif provider_name == 'snowflake':
        model_name = os.getenv('SNOWFLAKE_MODEL', 'Snowflake/snowflake-arctic-embed-s')

        try:
            return SnowflakeEmbeddingProvider(model_name=model_name)
        except Exception as e:
            logger.error(f"❌ Échec initialisation Snowflake: {e}")
            logger.warning("   Basculement vers mode sans embeddings")
            return NoEmbeddingProvider()

    elif provider_name == 'none':
        logger.info("ℹ️  Embeddings désactivés")
        return NoEmbeddingProvider()

    else:
        logger.warning(f"⚠️  Provider inconnu '{provider_name}' - embeddings désactivés")
        logger.info("   Providers disponibles: gemini, snowflake, none")
        return NoEmbeddingProvider()
