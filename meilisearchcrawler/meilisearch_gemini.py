"""
Module pour générer et ajouter des embeddings Gemini aux documents MeiliSearch.
Ce script peut être exécuté de manière autonome pour traiter les documents existants.
VERSION PROGRESSIVE OPTIMISÉE - Indexation immédiate pour libérer la mémoire.
"""

import os
import sys
import logging
import time
from typing import List
from pathlib import Path
from meilisearch_python_sdk import Client
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

    def process_missing_embeddings(self, index_name: str,
                                   batch_size: int = 50,
                                   gemini_batch_size: int = 100):
        """
        Trouve les documents sans embeddings, les génère et met à jour l'index.
        VERSION PROGRESSIVE: indexe immédiatement après génération des embeddings.

        Args:
            index_name: Nom de l'index MeiliSearch
            batch_size: Nombre de documents à récupérer de MeiliSearch par requête
            gemini_batch_size: Nombre d'embeddings à générer par requête Gemini
        """
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
        print(f"⚙️  Batch MeiliSearch: {batch_size} documents")
        print(f"⚙️  Batch Gemini: {gemini_batch_size} embeddings")
        print(f"🔄 Estimation: ~{(total_missing // gemini_batch_size) + 1} requêtes API Gemini")
        print(f"📦 Mode: Indexation progressive (mémoire optimisée)\n")

        with tqdm(total=total_missing, desc="📝 Génération", unit="doc", file=sys.stdout) as pbar:
            processed_docs_count = 0
            successful_updates = 0
            quota_exceeded = False

            while processed_docs_count < total_missing and not quota_exceeded:
                try:
                    # Récupérer un batch de documents sans embeddings
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

                # Préparer les textes pour l'embedding (buffer temporaire)
                texts_buffer = []
                doc_ids_buffer = []

                for doc in docs_to_process:
                    title = getattr(doc, 'title', '')
                    content = getattr(doc, 'content', '')
                    text = f"{title}\n{content}".strip()

                    if text:  # Ne traiter que les docs avec du contenu
                        texts_buffer.append(text)
                        doc_ids_buffer.append(doc.id)

                if not texts_buffer:
                    processed_docs_count += len(docs_to_process)
                    pbar.update(len(docs_to_process))
                    continue

                # INDEXATION PROGRESSIVE: traiter les textes par sous-batches Gemini
                # et indexer immédiatement après chaque génération
                for i in range(0, len(texts_buffer), gemini_batch_size):
                    sub_texts = texts_buffer[i:i + gemini_batch_size]
                    sub_doc_ids = doc_ids_buffer[i:i + gemini_batch_size]

                    # Générer les embeddings pour ce sous-batch
                    try:
                        embeddings = self.get_embeddings_batch(sub_texts)
                    except QuotaExceededError:
                        print("\n🛑 Quota Gemini dépassé. Arrêt du processus.")
                        quota_exceeded = True
                        break

                    # Préparer et indexer IMMÉDIATEMENT (ne pas stocker en mémoire)
                    docs_to_update = []
                    for doc_id, embedding in zip(sub_doc_ids, embeddings):
                        if embedding and len(embedding) == 768:
                            docs_to_update.append({
                                'id': doc_id,
                                '_vectors': {'default': embedding}
                            })

                    # Indexer ce sous-batch immédiatement
                    if docs_to_update:
                        try:
                            task = index.update_documents(docs_to_update)
                            # Attendre que la tâche se termine
                            self.client.wait_for_task(task.task_uid, timeout_in_ms=30000)
                            successful_updates += len(docs_to_update)

                            # Libérer la mémoire explicitement
                            del docs_to_update
                            del embeddings

                        except Exception as e:
                            print(f"\n❌ ERREUR: Mise à jour MeiliSearch: {e}")

                    # Petit délai pour éviter de saturer l'API
                    time.sleep(0.3)

                # Libérer les buffers après traitement complet du batch
                del texts_buffer
                del doc_ids_buffer

                processed_docs_count += len(docs_to_process)
                pbar.update(len(docs_to_process))

                # Petit délai entre les batches MeiliSearch
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

    def count_documents_stats(self, index_name: str):
        """Affiche des statistiques sur les documents avec/sans embeddings."""
        try:
            index = self.client.index(index_name)

            # Total de documents
            stats = index.get_stats()
            total_docs = stats.get('numberOfDocuments', 0)

            # Documents sans embeddings
            try:
                search_res = index.search('', {'filter': '_vectors.default NOT EXISTS', 'limit': 0})
                docs_without = search_res.get('estimatedTotalHits', 0)
            except:
                docs_without = "N/A"

            # Documents avec embeddings
            docs_with = total_docs - docs_without if isinstance(docs_without, int) else "N/A"

            print("\n" + "="*60)
            print("📊 STATISTIQUES DES EMBEDDINGS")
            print("="*60)
            print(f"📄 Total de documents: {total_docs}")
            print(f"✅ Avec embeddings: {docs_with}")
            print(f"❌ Sans embeddings: {docs_without}")
            if isinstance(docs_with, int) and total_docs > 0:
                percentage = (docs_with / total_docs) * 100
                print(f"📈 Taux de couverture: {percentage:.1f}%")
            print("="*60 + "\n")

        except Exception as e:
            print(f"❌ Erreur lors du calcul des statistiques: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Ajouter des embeddings Gemini aux documents MeiliSearch')
    parser.add_argument('--stats', action='store_true', help='Afficher uniquement les statistiques')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='Nombre de documents à récupérer par batch (défaut: 50)')
    parser.add_argument('--gemini-batch-size', type=int, default=100,
                       help='Nombre d\'embeddings à générer par requête Gemini (défaut: 100)')
    args = parser.parse_args()

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

        if args.stats:
            # Afficher uniquement les statistiques
            meili_gemini.count_documents_stats(INDEX_NAME)
        else:
            # Traiter les documents manquants
            meili_gemini.process_missing_embeddings(
                INDEX_NAME,
                batch_size=args.batch_size,
                gemini_batch_size=args.gemini_batch_size
            )

    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption utilisateur (Ctrl+C)")
        print("💡 Vous pouvez relancer le script pour continuer où il s'est arrêté")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Une erreur inattendue est survenue: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)