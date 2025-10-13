"""
Module pour générer et ajouter des embeddings Gemini aux documents MeiliSearch.
Ce script peut être exécuté de manière autonome pour traiter les documents existants.
"""

import os
import sys
import logging
import time
from typing import List
from pathlib import Path
import meilisearch
from google import genai
from dotenv import load_dotenv
from tqdm import tqdm

# --- Configuration ---
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configurer un logger dédié
gemini_logger = logging.getLogger("gemini_embedder")
gemini_logger.setLevel(logging.INFO)
if not gemini_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    gemini_logger.addHandler(handler)


class QuotaExceededError(Exception):
    """Exception levée lorsque le quota de l'API Gemini est dépassé."""
    pass


class MeiliSearchGemini:
    """Gère l'indexation avec embeddings Gemini dans MeiliSearch."""

    def __init__(self, meili_url: str, meili_key: str, gemini_api_key: str):
        self.client = meilisearch.Client(meili_url, meili_key)
        self.embedding_model = "text-embedding-004"

        try:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
            gemini_logger.info("✓ Gemini API client initialisé.")
        except Exception as e:
            gemini_logger.error(f"❌ Erreur lors de l'initialisation du client Gemini: {e}")
            self.gemini_client = None

        gemini_logger.info(f"✓ MeiliSearch connecté à {meili_url}")
        gemini_logger.info(f"✓ Modèle d'embedding: {self.embedding_model}")

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Génère des embeddings pour un lot de textes."""
        if not self.gemini_client:
            gemini_logger.error("Client Gemini non initialisé. Impossible de générer les embeddings.")
            return [[] for _ in texts]

        try:
            result = self.gemini_client.models.embed_content(
                model=self.embedding_model,
                contents=texts
            )
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            error_str = str(e).lower()
            if "quota" in error_str or "resource exhausted" in error_str:
                gemini_logger.error(f"🛑 Quota Gemini dépassé: {e}")
                raise QuotaExceededError(str(e))
            gemini_logger.error(f"❌ Erreur API Gemini: {e}")
            return [[] for _ in texts]

    def check_embedder_config(self, index_name: str) -> bool:
        """Vérifie que les embedders sont bien configurés."""
        try:
            index = self.client.index(index_name)
            settings = index.get_settings()
            embedders = settings.get('embedders', {})

            has_default = 'default' in embedders
            has_query = 'query' in embedders

            if has_default and has_query:
                gemini_logger.info("✓ Embedders 'default' et 'query' déjà configurés")
                return True
            else:
                missing = []
                if not has_default:
                    missing.append('default')
                if not has_query:
                    missing.append('query')
                gemini_logger.warning(f"⚠️  Embedders manquants: {', '.join(missing)}")
                gemini_logger.warning("   Exécutez d'abord: python configure_and_check_meilisearch.py")
                return False
        except Exception as e:
            gemini_logger.error(f"❌ Erreur lors de la vérification: {e}")
            return False

    def process_missing_embeddings(self, index_name: str, batch_size: int = 50):
        """Trouve les documents sans embeddings, les génère et met à jour l'index."""
        # Vérifier d'abord que les embedders sont configurés
        if not self.check_embedder_config(index_name):
            print("\n❌ Configuration incomplète. Arrêt du processus.")
            return

        index = self.client.index(index_name)
        print("\n🔍 Recherche des documents sans embeddings...")

        try:
            search_res = index.search('', {'filter': '_vectors.default NOT EXISTS', 'limit': 0})
            total_missing = search_res.get('estimatedTotalHits', 0)
        except Exception as e:
            print(f"❌ ERREUR: Impossible de compter les documents: {e}")
            return

        if total_missing == 0:
            print("🎉 Tous les documents ont déjà des embeddings. Aucune action requise.")
            return

        print(f"📊 Trouvé: {total_missing} documents sans embeddings")
        print(f"⚙️  Batch size: {batch_size} documents")
        print(f"🔄 Estimation: ~{(total_missing // batch_size) + 1} requêtes API Gemini\n")

        with tqdm(total=total_missing, desc="📝 Génération", unit="doc", file=sys.stdout) as pbar:
            processed_docs_count = 0
            successful_updates = 0
            quota_exceeded = False

            while processed_docs_count < total_missing and not quota_exceeded:
                try:
                    docs_to_process = index.get_documents({
                        'filter': '_vectors.default NOT EXISTS',
                        'limit': batch_size,
                        'fields': ['id', 'title', 'content']
                    }).results
                except Exception as e:
                    print(f"\n❌ ERREUR: Récupération des documents: {e}")
                    time.sleep(5)
                    continue

                if not docs_to_process:
                    break  # Terminé

                # Préparer les textes pour l'embedding
                texts_to_embed = []
                doc_ids = []

                for doc in docs_to_process:
                    title = getattr(doc, 'title', '')
                    content = getattr(doc, 'content', '')
                    text = f"{title}\n{content}".strip()

                    if text:  # Ne traiter que les docs avec du contenu
                        texts_to_embed.append(text)
                        doc_ids.append(doc.id)

                if not texts_to_embed:
                    processed_docs_count += len(docs_to_process)
                    pbar.update(len(docs_to_process))
                    continue

                # Générer les embeddings
                try:
                    embeddings = self.get_embeddings_batch(texts_to_embed)
                except QuotaExceededError:
                    print("\n🛑 Quota Gemini dépassé. Arrêt du processus.")
                    quota_exceeded = True
                    break

                # Préparer les mises à jour
                docs_to_update = []
                for doc_id, embedding in zip(doc_ids, embeddings):
                    if embedding and len(embedding) == 768:
                        docs_to_update.append({
                            'id': doc_id,
                            '_vectors': {'default': embedding}
                        })

                # Mettre à jour MeiliSearch
                if docs_to_update:
                    try:
                        task = index.update_documents(docs_to_update)
                        # Attendre que la tâche se termine
                        self.client.wait_for_task(task.task_uid, timeout_in_ms=30000)
                        successful_updates += len(docs_to_update)
                    except Exception as e:
                        print(f"\n❌ ERREUR: Mise à jour MeiliSearch: {e}")

                processed_docs_count += len(docs_to_process)
                pbar.update(len(docs_to_process))

                # Petit délai pour éviter de saturer l'API
                time.sleep(0.5)

        # Résumé
        print("\n" + "="*60)
        if quota_exceeded:
            print(f"⚠️  Processus interrompu (quota dépassé)")
        else:
            print(f"✅ Processus terminé")
        print(f"📊 Documents traités: {processed_docs_count}")
        print(f"✓  Embeddings ajoutés: {successful_updates}")
        if processed_docs_count > successful_updates:
            print(f"⚠️  Échecs: {processed_docs_count - successful_updates}")
        print("="*60)


if __name__ == "__main__":
    MEILI_URL = os.getenv("MEILI_URL")
    MEILI_KEY = os.getenv("MEILI_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")

    if not all([MEILI_URL, MEILI_KEY, GEMINI_API_KEY]):
        print("❌ ERREUR: MEILI_URL, MEILI_KEY, et GEMINI_API_KEY doivent être définis dans .env")
        sys.exit(1)

    try:
        meili_gemini = MeiliSearchGemini(
            meili_url=MEILI_URL,
            meili_key=MEILI_KEY,
            gemini_api_key=GEMINI_API_KEY
        )
        meili_gemini.process_missing_embeddings(INDEX_NAME)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption utilisateur (Ctrl+C)")
        print("💡 Vous pouvez relancer le script pour continuer où il s'est arrêté")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Une erreur inattendue est survenue: {e}")
        sys.exit(1)