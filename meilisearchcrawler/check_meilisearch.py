import os
import sys
import requests
from dotenv import load_dotenv
from meilisearch_python_sdk import Client
from meilisearch_python_sdk.errors import MeilisearchApiError, MeilisearchTimeoutError

# --- Chargement de la configuration ---
print("⚙️  Chargement de la configuration...")
load_dotenv()

MEILI_URL = os.getenv("MEILI_URL", "http://meilisearch:7700")
API_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Validation ---
if not all([MEILI_URL, API_KEY]):
    print("\n❌ ERREUR: MEILI_URL et MEILI_KEY doivent être définis.")
    sys.exit(1)

print(f"   - URL Meilisearch: {MEILI_URL}")
print(f"   - Index: {INDEX_NAME}")


def check_index_stats():
    """Vérifie les statistiques de l'index"""
    try:
        client = Client(url=MEILI_URL, api_key=API_KEY)
        index = client.index(INDEX_NAME)

        stats = index.get_stats()
        print(f"\n📊 Statistiques de l'index '{INDEX_NAME}':")
        print(f"   - Nombre de documents: {stats.number_of_documents}")
        print(f"   - En cours d'indexation: {stats.is_indexing}")

        # Compter les documents avec et sans embeddings
        try:
            with_embeddings = index.search("", filter='_vectors.default EXISTS', limit=0)
            without_embeddings = index.search("", filter='_vectors.default NOT EXISTS', limit=0)

            print(f"\n🔍 Embeddings:")
            print(f"   - Avec embeddings: {with_embeddings.estimated_total_hits}")
            print(f"   - Sans embeddings: {without_embeddings.estimated_total_hits}")
        except Exception as e:
            print(f"   ⚠️  Impossible de vérifier les embeddings (peut-être pas configurés): {e}")

        # Vérifier la configuration des embedders
        settings = index.get_settings()
        embedders = settings.embedders or {}
        print(f"\n⚙️  Embedders configurés: {list(embedders.keys())}")

        return stats.number_of_documents
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return 0


def activate_experimental_features():
    """Active les features expérimentales"""
    try:
        print("\n🔄 Activation des features expérimentales...")
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "vectorStore": True,
        }
        r = requests.patch(f"{MEILI_URL}/experimental-features", json=payload, headers=headers)
        r.raise_for_status()
        print("✅ Features expérimentales activées.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Erreur: {e}")
        return False


def configure_embedders():
    """Configure les embedders default et query"""
    if not GEMINI_API_KEY:
        print("\n❌ ERREUR: GEMINI_API_KEY doit être défini pour configurer l'embedder Gemini.")
        return False
    try:
        client = Client(url=MEILI_URL, api_key=API_KEY)
        index = client.index(INDEX_NAME)

        print("\n🔄 Configuration des embedders...")

        embedder_url = "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent"

        settings_payload = {
            "embedders": {
                "default": {
                    "source": "userProvided",
                    "dimensions": 768
                },
                "query": {
                    "source": "rest",
                    "url": embedder_url,
                    "apiKey": GEMINI_API_KEY,
                    "request": {
                        "model": "models/text-embedding-004",
                        "content": {
                            "parts": [
                                {"text": "{{text}}"}
                            ]
                        }
                    },
                    "response": {
                        "embedding": {
                            "values": "{{embedding}}"
                        }
                    },
                    "dimensions": 768
                }
            }
        }

        task = index.update_settings(settings_payload)
        print(f"   - Tâche soumise (UID: {task.task_uid})")
        print("   ⏳ Attente de la configuration (peut prendre 1-2 minutes)...")

        final_task = client.wait_for_task(task.task_uid, timeout_in_ms=120000)

        if final_task.status == "succeeded":
            print("✅ Embedders configurés avec succès !")
            print("   - 'default': userProvided (768 dimensions)")
            print("   - 'query': Gemini text-embedding-004")
            return True
        else:
            print(f"❌ Échec de la configuration:")
            print(f"   Status: {final_task.status}")
            if final_task.error:
                print(f"   Erreur: {final_task.error}")
            return False

    except MeilisearchTimeoutError:
        print("⏱️  Timeout - vérification manuelle du statut...")
        try:
            task_status = client.get_task(task.task_uid)
            if task_status.status == "succeeded":
                print("✅ Configuration réussie (vérification manuelle)")
                return True
            else:
                print(f"❌ Status: {task_status.status}")
                return False
        except:
            return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False


def delete_all_documents():
    """Supprime tous les documents de l'index"""
    try:
        client = Client(url=MEILI_URL, api_key=API_KEY)
        index = client.index(INDEX_NAME)

        response = input("\n⚠️  ATTENTION: Voulez-vous VRAIMENT supprimer tous les documents ? (oui/non): ")
        if response.lower() != "oui":
            print("Annulé.")
            return False

        print("🗑️  Suppression de tous les documents...")
        task = index.delete_all_documents()
        client.wait_for_task(task.task_uid)
        print("✅ Tous les documents ont été supprimés.")
        return True
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False


def main_menu():
    """Menu principal"""
    while True:
        print("\n" + "=" * 60)
        print("🔧 CONFIGURATION ET DIAGNOSTIC MEILISEARCH")
        print("=" * 60)

        print("\n1. 📊 Vérifier l'état de l'index")
        print("2. ⚙️  Configurer les embedders (default + query)")
        print("3. 🔄 Activer les features expérimentales")
        print("4. 🗑️  Supprimer tous les documents")
        print("5. 🚀 Configuration complète (features + embedders)")
        print("6. ❌ Quitter")

        choice = input("\nVotre choix (1-6): ").strip()

        if choice == "1":
            check_index_stats()
        elif choice == "2":
            configure_embedders()
        elif choice == "3":
            activate_experimental_features()
        elif choice == "4":
            delete_all_documents()
        elif choice == "5":
            if activate_experimental_features():
                configure_embedders()
        elif choice == "6":
            print("\n👋 Au revoir!")
            break
        else:
            print("❌ Choix invalide")


if __name__ == "__main__":
    doc_count = check_index_stats()
    if doc_count > 0:
        print(f"\n💡 Vous avez {doc_count} documents indexés.")
        print("   Si les recherches ne fonctionnent pas, c'est probablement")
        print("   parce que l'embedder 'query' n'est pas configuré.")
    main_menu()
