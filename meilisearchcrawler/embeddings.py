from abc import ABC, abstractmethod
from typing import List, Optional
import logging
import os
import requests


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

    @abstractmethod
    def get_provider_name(self) -> str:
        """Retourne le nom générique du provider (ex: 'gemini')."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Retourne le nom spécifique du modèle (ex: 'intfloat/multilingual-e5-base')."""
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
        """Génère des embeddings avec l'API Gemini"""
        try:
            result = self.client.models.embed_content(
                model=f"models/{self.model_name}",
                contents=texts
            )
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'encodage avec Gemini: {e}")
            return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return self.embedding_dim

    def get_provider_name(self) -> str:
        return "gemini"

    def get_model_name(self) -> str:
        return self.model_name


class HuggingFaceInferenceAPIEmbeddingProvider(EmbeddingProvider):
    """Provider utilisant une API d'inférence Hugging Face (comme text-embeddings-inference)"""

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

        try:
            import requests
        except ImportError:
            raise ImportError("Le package 'requests' est requis. Installez-le avec: pip install requests")

        logger.info(f"✓ HuggingFace Inference API provider initialisé pour le modèle {model_name} sur {self.api_url}")
        # Test connection
        try:
            # remove /embed from url to get /info
            base_url = self.api_url.rsplit('/', 1)[0]
            response = requests.get(f"{base_url}/info", timeout=5)
            response.raise_for_status()
            info = response.json()
            logger.info(f"✓ Connexion à l'API d'inférence réussie: version {info.get('version')}, modèle {info.get('model_id')}")
            # Override model_name with info from API if they don't match
            if self.model_name != info.get('model_id'):
                logger.warning(f"Le modèle configuré ({self.model_name}) est différent de celui de l'API ({info.get('model_id')}). Utilisation du modèle de l'API.")
                self.model_name = info.get('model_id')
                # Update dimension based on new model name
                self.embedding_dim = self.MODEL_DIMENSIONS.get(self.model_name, self.embedding_dim)

            # L'API /info ne retourne pas la dimension, donc on fait un test
            try:
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
                        logger.warning(f"La dimension configurée ({self.embedding_dim}D) est différente de celle détectée ({detected_dim}D). Utilisation de la dimension détectée.")
                        self.embedding_dim = detected_dim
                    else:
                        logger.info(f"✓ Dimension vérifiée: {self.embedding_dim}D")
            except Exception as e:
                logger.warning(f"Impossible de vérifier la dimension via un test: {e}. Utilisation de {self.embedding_dim}D")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Impossible de se connecter à l'API d'inférence Hugging Face sur {self.api_url}: {e}")
        except Exception as e:
            logger.warning(f"Impossible de vérifier les informations de l'API d'inférence: {e}")


    def encode(self, texts: List[str]) -> List[List[float]]:
        """Génère des embeddings avec l'API d'inférence Hugging Face"""
        try:
            response = requests.post(
                self.api_url,
                json={"inputs": texts, "normalize": True, "truncate": True},
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            embeddings = response.json()
            return embeddings
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Erreur API Hugging Face: {e}")
            return [[] for _ in texts]
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'encodage avec l'API Hugging Face: {e}")
            return [[] for _ in texts]

    def get_embedding_dim(self) -> int:
        return self.embedding_dim

    def get_provider_name(self) -> str:
        return "huggingface"

    def get_model_name(self) -> str:
        return self.model_name


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

    def get_provider_name(self) -> str:
        return "none"

    def get_model_name(self) -> str:
        return "none"


def create_embedding_provider(provider_name: Optional[str] = None) -> EmbeddingProvider:
    """
    Factory pour créer un provider d'embeddings basé sur la configuration

    Args:\
        provider_name: Nom du provider ('gemini', 'huggingface', 'none')
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

    elif provider_name == 'huggingface':
        model_name = os.getenv('HUGGINGFACE_MODEL', 'intfloat/multilingual-e5-small')
        api_url = os.getenv('HUGGINGFACE_API_URL', 'http://localhost:8081/embed')

        try:
            return HuggingFaceInferenceAPIEmbeddingProvider(model_name=model_name, api_url=api_url)
        except Exception as e:
            logger.error(f"❌ Échec initialisation HuggingFace Inference API: {e}")
            logger.warning("   Basculement vers mode sans embeddings")
            return NoEmbeddingProvider()

    elif provider_name == 'none':
        logger.info("ℹ️  Embeddings désactivés")
        return NoEmbeddingProvider()

    else:
        logger.warning(f"⚠️  Provider inconnu '{provider_name}' - embeddings désactivés")
        logger.info("   Providers disponibles: gemini, huggingface, none")
        return NoEmbeddingProvider()
