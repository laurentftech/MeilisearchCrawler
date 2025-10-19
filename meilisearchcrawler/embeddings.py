from abc import ABC, abstractmethod
from typing import List, Optional
import logging
import os

# Forcer l'utilisation du CPU avant tous les imports
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["FORCE_CUDA"] = "0"
os.environ["FORCE_CPU"] = "1"

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Interface abstraite pour les providers d'embeddings"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.embedding_dim = None  # Sera défini par les sous-classes

    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        """"Génère des embeddings pour une liste de textes"""
        pass

    @abstractmethod
    def get_embedding_dim(self) -> int:
        """"Retourne la dimension des embeddings"""

    @abstractmethod
    def get_provider_name(self) -> str:
        """"Retourne le nom générique du provider (ex: 'gemini')."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """"Retourne le nom spécifique du modèle (ex: 'intfloat/multilingual-e5-base')."""
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
        """"Génère des embeddings avec Gemini"""
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

    def get_provider_name(self) -> str:
        return "gemini"

    def get_model_name(self) -> str:
        return self.model_name


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """"Provider utilisant Sentence Transformers (local)"""

    # Dimensions selon les modèles courants
    MODEL_DIMENSIONS = {
        'intfloat/multilingual-e5-base': 768,
        'Snowflake/snowflake-arctic-embed-xs': 384,
        'Snowflake/snowflake-arctic-embed-s': 384,
        'Snowflake/snowflake-arctic-embed-m': 768,
        'intfloat/multilingual-e5-base': 768,
        'Snowflake/snowflake-arctic-embed-l': 1024,
    }

    def __init__(self, model_name: str = "intfloat/multilingual-e5-base"):
        super().__init__(model_name)
        self.embedding_dim = self.MODEL_DIMENSIONS.get(model_name, 768) # Default to 768 for e5-base

        try:
            # Import torch et forcer CPU explicitement
            import torch
            torch.set_num_threads(1)

            # Vérifier qu'on n'utilise pas CUDA
            if torch.cuda.is_available():
                logger.warning("CUDA is available but will be IGNORED - forcing CPU")

            from sentence_transformers import SentenceTransformer
            logger.info(f"📦 Chargement du modèle Sentence Transformer: {model_name}...")
            self.model = SentenceTransformer(model_name, trust_remote_code=True, device="cpu")
            logger.info(f"✓ Sentence Transformer initialisé ({self.embedding_dim}D) sur CPU")
        except ImportError:
            raise ImportError("Le package 'sentence-transformers' est requis. Installez-le avec: pip install sentence-transformers")
        except Exception as e:
            raise RuntimeError(f"Impossible de charger le modèle Sentence Transformer {model_name}: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """"Génère des embeddings avec Sentence Transformer"""
        try:
            embeddings = self.model.encode(
                texts,
                show_progress_bar=False,
                convert_to_numpy=True
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"❌ Erreur Sentence Transformer encoding: {e}")
            return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return self.embedding_dim

    def get_provider_name(self) -> str:
        return "sentence_transformer"

    def get_model_name(self) -> str:
        return self.model_name


class NoEmbeddingProvider(EmbeddingProvider):
    """Provider vide (pas d'embeddings)"""

    def __init__(self):
        super().__init__("none")
        self.embedding_dim = 0

    def encode(self, texts: List[str]) -> List[List[float]]:
        """"Retourne des embeddings vides"""
        return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return 0

    def get_provider_name(self) -> str:
        return "none"

    def get_model_name(self) -> str:
        return "none"


def create_embedding_provider(provider_name: Optional[str] = None) -> EmbeddingProvider:
    """
    Factory pour créer un provider d'embeddings basé sur la configuration

    Args:\
        provider_name: Nom du provider ('gemini', 'sentence_transformer', 'none')
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

    elif provider_name == 'sentence_transformer':
        model_name = os.getenv('SENTENCE_TRANSFORMER_MODEL', 'intfloat/multilingual-e5-base')

        try:
            return SentenceTransformerEmbeddingProvider(model_name=model_name)
        except Exception as e:
            logger.error(f"❌ Échec initialisation Sentence Transformer: {e}")
            logger.warning("   Basculement vers mode sans embeddings")
            return NoEmbeddingProvider()

    elif provider_name == 'none':
        logger.info("ℹ️  Embeddings désactivés")
        return NoEmbeddingProvider()

    else:
        logger.warning(f"⚠️  Provider inconnu '{provider_name}' - embeddings désactivés")
        logger.info("   Providers disponibles: gemini, sentence_transformer, none")
        return NoEmbeddingProvider()
