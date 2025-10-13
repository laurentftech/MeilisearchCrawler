"""
Module pour générer et ajouter des embeddings Gemini aux documents MeiliSearch.
Ce script peut être exécuté de manière autonome pour traiter les documents existants.
"""

import os
import sys
import logging
import time
from typing import List, Dict
from pathlib import Path
import meilisearch
from google import genai
from dotenv import load_dotenv
from tqdm import tqdm

# --- Configuration ---
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configurer un logger dédié pour éviter les interférences
gemini_logger = logging.getLogger("gemini_embedder")
gemini_logger.setLevel(logging.INFO)
if not gemini_logger.handlers:
    handler = logging.StreamHandler(sys.stdout) # Assurer l'affichage dans le dashboard
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
            result = self.gemini_client.models.embed_content(model=self.embedding_model, contents=texts)
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            if "quota" in str(e).lower():
                gemini_logger.error(f"🛑 Quota Gemini dépassé: {e}")
                raise QuotaExceededError(str(e))
            gemini_logger.error(f"Erreur API Gemini: {e}")
            return [[] for _ in texts] # Retourner une liste vide en cas d'erreur

    def setup_index_for_embeddings(self, index_name: str):
        """Configure l'index pour accepter les embeddings fournis par l'utilisateur."""
        print(f"Configuration de l'index '{index_name}' pour la recherche sémantique...")
        try:
            task = self.client.index(index_name).update_embedders({
                'default': {
                    'source': 'userProvided',
                    'dimensions': 768  # Le modèle text-embedding-004 de Gemini a 768 dimensions
                }
            })
            self.client.wait_for_task(task.task_uid, timeout_in_ms=5000)
            print(f"✓ Index '{index_name}' configuré avec un embedder de 768 dimensions.")
        except Exception as e:
            print(f"⚠️  Impossible de mettre à jour les embedders (peut-être déjà configuré): {e}")

    def process_missing_embeddings(self, index_name: str, batch_size: int = 50):
        """Trouve les documents sans embeddings, les génère et met à jour l'index."""
        index = self.client.index(index_name)
        print("\nDébut du processus d'ajout des embeddings manquants...")

        try:
            search_res = index.search('', {'filter': '_vectors NOT EXISTS', 'limit': 0})
            total_missing = search_res.get('estimatedTotalHits', 0)
        except Exception as e:
            print(f"ERREUR: Impossible de compter les documents manquants dans Meilisearch: {e}")
            return

        if total_missing == 0:
            print("🎉 Tous les documents ont déjà des embeddings. Aucune action requise.")
            return

        print(f"Trouvé: {total_missing} documents sans embeddings. Lancement du processus...")

        with tqdm(total=total_missing, desc="Génération des Embeddings", unit="doc", file=sys.stdout) as pbar:
            processed_docs_count = 0
            quota_exceeded = False
            while processed_docs_count < total_missing and not quota_exceeded:
                try:
                    docs_to_process = index.get_documents({
                        'filter': '_vectors NOT EXISTS',
                        'limit': batch_size,
                        'fields': ['id', 'title', 'content']
                    }).results
                except Exception as e:
                    print(f"\nERREUR: Impossible de récupérer les documents depuis Meilisearch: {e}")
                    time.sleep(5)
                    continue

                if not docs_to_process:
                    break # Terminé

                texts_to_embed = [
                    f"{getattr(doc, 'title', '')}\n{getattr(doc, 'content', '')}".strip()
                    for doc in docs_to_process
                ]
                doc_ids = [doc.id for doc in docs_to_process]

                try:
                    embeddings = self.get_embeddings_batch(texts_to_embed)
                except QuotaExceededError:
                    print("\n🛑 Quota Gemini dépassé. Arrêt du processus d'embedding.")
                    quota_exceeded = True
                    continue

                docs_to_update = []
                for doc_id, embedding in zip(doc_ids, embeddings):
                    if embedding:
                        docs_to_update.append({'id': doc_id, '_vectors': {'default': embedding}})

                if docs_to_update:
                    try:
                        index.update_documents(docs_to_update)
                    except Exception as e:
                        print(f"\nERREUR: Impossible de mettre à jour le lot dans Meilisearch: {e}")
                
                processed_docs_count += len(docs_to_process)
                pbar.update(len(docs_to_process))

        if quota_exceeded:
            print(f"\n⚠️  Processus interrompu après avoir traité {processed_docs_count} documents en raison du dépassement du quota Gemini.")
        else:
            print(f"\n✅ Processus terminé. {processed_docs_count} documents ont été traités.")


if __name__ == "__main__":
    MEILI_URL = os.getenv("MEILI_URL")
    MEILI_KEY = os.getenv("MEILI_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")

    if not all([MEILI_URL, MEILI_KEY, GEMINI_API_KEY]):
        print("ERREUR: MEILI_URL, MEILI_KEY, et GEMINI_API_KEY doivent être définis dans votre fichier .env")
        sys.exit(1)

    try:
        meili_gemini = MeiliSearchGemini(
            meili_url=MEILI_URL,
            meili_key=MEILI_KEY,
            gemini_api_key=GEMINI_API_KEY
        )
        meili_gemini.setup_index_for_embeddings(INDEX_NAME)
        meili_gemini.process_missing_embeddings(INDEX_NAME)
    except Exception as e:
        print(f"\nUne erreur inattendue est survenue: {e}")
        sys.exit(1)
