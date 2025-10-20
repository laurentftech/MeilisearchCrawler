"""
Configuration automatique de MeiliSearch pour les embeddings multi-providers.
Supporte: Gemini, HuggingFace, et None
"""

import os
import sys
import requests
from dotenv import load_dotenv
from pathlib import Path
from meilisearch_python_sdk import Client
from meilisearch_python_sdk.errors import MeilisearchApiError, MeilisearchTimeoutError

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))
from meilisearchcrawler.embeddings import create_embedding_provider

# --- Chargement de la configuration ---
print("⚙️  Chargement de la configuration...")
load_dotenv()

MEILI_URL = os.getenv("MEILI_URL", "http://localhost:7700")
API_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "none").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Validation ---
if not all([MEILI_URL, API_KEY]):
    print("\n❌ ERREUR: MEILI_URL et MEILI_KEY doivent être définis.")
    sys.exit(1)

if EMBEDDING_PROVIDER == "gemini" and not GEMINI_API_KEY:
    print("\n❌ ERREUR: GEMINI_API_KEY doit être défini pour utiliser Gemini.")
    sys.exit(1)

print(f"   - URL Meilisearch: {MEILI_URL}")
print(f"   - Index: {INDEX_NAME}")
print(f"   - Provider: {EMBEDDING_PROVIDER}")

# --- Déterminer les dimensions d'embeddings ---
try:
    provider = create_embedding_provider(EMBEDDING_PROVIDER)
    embedding_dim = provider.get_embedding_dim()

    if embedding_dim == 0:
        print("\n⚠️  Aucun provider d'embeddings actif.")
        print("   MeiliSearch sera configuré SANS embeddings (recherche texte uniquement).")
        use_embeddings = False
    else:
        print(f"   - Dimensions: {embedding_dim}D")
        use_embeddings = True
except Exception as e:
    print(f"\n❌ ERREUR lors de l'initialisation du provider: {e}")
    sys.exit(1)

# --- Activation des features expérimentales via PATCH ---
if use_embeddings:
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
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Impossible d'activer les features expérimentales: {e}")
        print("   - Vérifiez que Meilisearch est bien démarré et que la clé API est correcte.")

# --- Connexion Meilisearch ---
try:
    client = Client(url=MEILI_URL, api_key=API_KEY)
    index = client.index(INDEX_NAME)

    # --- Configuration des embedders ---
    print("\n🔄 Mise à jour des embedders...")

    if not use_embeddings:
        settings_payload = {"embedders": {}}
        print("   - Configuration: AUCUN embedder (recherche texte uniquement)")

    elif EMBEDDING_PROVIDER == "gemini":
        embedder_url = "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent"
        settings_payload = {
            "embedders": {
                "default": {"source": "userProvided", "dimensions": 768},
                "query": {
                    "source": "rest",
                    "url": embedder_url,
                    "apiKey": GEMINI_API_KEY,
                    "request": {"model": "models/text-embedding-004", "content": {"parts": [{"text": "{{text}}"}]}},
                    "response": {"embedding": {"values": "{{embedding}}"}},
                    "dimensions": 768
                }
            }
        }
        print("   - Configuration: Gemini (768D)")
        print("   - Embedder 'default': userProvided (documents)")
        print("   - Embedder 'query': REST API Gemini (requêtes)")

    elif EMBEDDING_PROVIDER == "huggingface":
        settings_payload = {
            "embedders": {
                "default": {"source": "userProvided", "dimensions": embedding_dim}
            }
        }
        print(f"   - Configuration: Embeddings ({embedding_dim}D)")
        print("   - Embedder 'default': userProvided (documents + requêtes)")
        print("   - Note: Les embeddings seront calculés par l'API backend ou le crawler")

    else:
        print(f"\n❌ Provider '{EMBEDDING_PROVIDER}' non supporté.")
        sys.exit(1)

    # Appliquer la configuration
    task = index.update_settings(settings_payload)
    print(f"   - Tâche soumise (UID: {task.task_uid}), en attente de résolution...")

    timeout = 120000 if EMBEDDING_PROVIDER == "gemini" else 30000
    if EMBEDDING_PROVIDER == "gemini":
        print("   ⏳ Cela peut prendre jusqu'à 2 minutes (test de connexion à Gemini)...")
    else:
        print("   ⏳ En cours...")

    try:
        final_task = client.wait_for_task(task.task_uid, timeout_in_ms=timeout)

        if final_task.status == "succeeded":
            print("\n✅ Embedders configurés avec succès !")
            print("\n📋 Résumé de la configuration:")
            print(f"   - Provider: {EMBEDDING_PROVIDER}")
            print(f"   - Dimensions: {embedding_dim}D" if use_embeddings else "   - Embeddings: Désactivés")
        else:
            print("\n❌ La mise à jour a échoué :")
            print(f"   Status: {final_task.status}")
            if final_task.error:
                print(f"   Erreur: {final_task.error}")

    except MeilisearchTimeoutError:
        print("\n⏱️  Timeout dépassé, vérification manuelle du statut de la tâche...")
        task_status = client.get_task(task.task_uid)
        print(f"   Status actuel: {task_status.status}")
        if task_status.status == "succeeded":
            print("✅ La configuration a réussi !")
        elif task_status.status == "failed" and task_status.error:
            print(f"❌ La configuration a échoué : {task_status.error}")
        else:
            print(f"⏳ La tâche est toujours en cours ({task_status.status})")

except MeilisearchApiError as e:
    print(f"\n❌ ERREUR API Meilisearch: {e}")
except Exception as e:
    print(f"\n❌ Erreur inattendue: {e}")
    import traceback
    traceback.print_exc()
