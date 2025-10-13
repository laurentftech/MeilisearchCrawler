import os
import sys
import requests
from dotenv import load_dotenv
import meilisearch
from meilisearch.errors import MeilisearchApiError, MeilisearchTimeoutError

# --- Chargement de la configuration ---
print("⚙️  Chargement de la configuration...")
load_dotenv()

MEILI_URL = os.getenv("MEILI_URL", "http://meilisearch:7700")
API_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Validation ---
if not all([MEILI_URL, API_KEY, GEMINI_API_KEY]):
    print("\n❌ ERREUR: MEILI_URL, MEILI_KEY, et GEMINI_API_KEY doivent être définis.")
    sys.exit(1)

print(f"   - URL Meilisearch: {MEILI_URL}")
print(f"   - Index: {INDEX_NAME}")

# --- Activation des features expérimentales via PATCH ---
try:
    print("\n🔄 Activation des features expérimentales...")
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "multimodal": True,
        "vectorStoreSetting": True,
        "compositeEmbedders": True,
        "chatCompletions": True
    }
    r = requests.patch(f"{MEILI_URL}/experimental-features", json=payload, headers=headers)
    r.raise_for_status()
    print("✅ Features expérimentales activées.")
except requests.exceptions.RequestException as e:
    print(f"⚠️  Impossible d'activer les features expérimentales: {e}")
    print("   - Vérifiez que Meilisearch est bien démarré et que la clé API est correcte.")

# --- Connexion Meilisearch ---
try:
    client = meilisearch.Client(MEILI_URL, API_KEY)
    index = client.index(INDEX_NAME)

    # --- Configuration des embedders ---
    print("\n🔄 Mise à jour des embedders...")

    # Construction de l'URL avec la clé API Gemini
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
                "request": {
                    "model": "models/text-embedding-004",
                    "content": {
                        "parts": [
                            {"text": "{{text}}"}
                        ]
                    }
                },
                "headers": {
                    "x-goog-api-key": GEMINI_API_KEY
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
    print(f"   - Tâche soumise (UID: {task.task_uid}), en attente de résolution...")
    print("   ⏳ Cela peut prendre jusqu'à 2 minutes (test de connexion à Gemini)...")

    try:
        final_task = client.wait_for_task(task.task_uid, timeout_in_ms=120000)  # 2 minutes

        if final_task.status == "succeeded":
            print("\n✅ Embedders configurés avec succès !")
        else:
            print("\n❌ La mise à jour a échoué :")
            print(f"   Status: {final_task.status}")
            if hasattr(final_task, 'error') and final_task.error:
                print(f"   Erreur: {final_task.error}")

    except MeilisearchTimeoutError:
        print("\n⏱️  Timeout dépassé, vérification manuelle du statut de la tâche...")
        # Vérifier manuellement le statut
        task_status = client.get_task(task.task_uid)
        print(f"   Status actuel: {task_status.status}")

        if task_status.status == "succeeded":
            print("✅ La configuration a réussi !")
        elif task_status.status == "failed":
            print("❌ La configuration a échoué :")
            if hasattr(task_status, 'error') and task_status.error:
                print(f"   Erreur: {task_status.error}")
        else:
            print(f"⏳ La tâche est toujours en cours ({task_status.status})")
            print("   Vous pouvez vérifier plus tard avec:")
            print(f"   curl -H 'Authorization: Bearer {API_KEY}' {MEILI_URL}/tasks/{task.task_uid}")

except MeilisearchApiError as e:
    print(f"\n❌ ERREUR API Meilisearch: {e}")
except Exception as e:
    print(f"\n❌ Erreur inattendue: {e}")