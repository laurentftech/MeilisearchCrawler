"""
Configuration automatique de MeiliSearch pour les embeddings multi-providers.
Supporte: Gemini, Snowflake Arctic Embed, et None
"""

import os
import sys
import requests
from dotenv import load_dotenv
from pathlib import Path
import meilisearch
from meilisearch.errors import MeilisearchApiError, MeilisearchTimeoutError
from transformers.models.distilbert.modeling_distilbert import Embeddings

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))
from meilisearchcrawler.embeddings import create_embedding_provider

# --- Chargement de la configuration ---
print("⚙️  Chargement de la configuration...")
load_dotenv()

MEILI_URL = os.getenv("MEILI_URL", "http://meilisearch:7700")
API_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "none").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")

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

    if not use_embeddings:
        # Désactiver les embeddings
        settings_payload = {
            "embedders": {}
        }
        print("   - Configuration: AUCUN embedder (recherche texte uniquement)")

    elif EMBEDDING_PROVIDER == "gemini":
        # Configuration Gemini (REST embedder pour les requêtes utilisateur)
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
        print("   - Configuration: Gemini (768D)")
        print("   - Embedder 'default': userProvided (documents)")
        print("   - Embedder 'query': REST API Gemini (requêtes)")

    elif EMBEDDING_PROVIDER == "snowflake" or EMBEDDING_PROVIDER == "sentence_transformer":
        # Configuration Snowflake (userProvided uniquement - le calcul se fait côté crawler/API)
        settings_payload = {
            "embedders": {
                "default": {
                    "source": "userProvided",
                    "dimensions": embedding_dim
                }
            }
        }
        print(f"   - Configuration: Embeddings ({embedding_dim}D)")
        print("   - Embedder 'default': userProvided (documents + requêtes)")
        print("   - Note: Les embeddings de requêtes seront calculés par l'API backend")

    else:
        print(f"\n❌ Provider '{EMBEDDING_PROVIDER}' non supporté.")
        sys.exit(1)

    # Appliquer la configuration
    task = index.update_settings(settings_payload)
    print(f"   - Tâche soumise (UID: {task.task_uid}), en attente de résolution...")

    if EMBEDDING_PROVIDER == "gemini":
        print("   ⏳ Cela peut prendre jusqu'à 2 minutes (test de connexion à Gemini)...")
        timeout = 120000  # 2 minutes
    else:
        print("   ⏳ En cours...")
        timeout = 30000   # 30 secondes

    try:
        final_task = client.wait_for_task(task.task_uid, timeout_in_ms=timeout)

        if final_task.status == "succeeded":
            print("\n✅ Embedders configurés avec succès !")
            print("\n📋 Résumé de la configuration:")
            print(f"   - Provider: {EMBEDDING_PROVIDER}")
            print(f"   - Dimensions: {embedding_dim}D" if use_embeddings else "   - Embeddings: Désactivés")

            if EMBEDDING_PROVIDER == "gemini":
                print("   - Documents: userProvided (calculés par le crawler)")
                print("   - Requêtes: REST API Gemini")
            elif EMBEDDING_PROVIDER == "snowflake" or EMBEDDING_PROVIDER == "sentence_transformer":
                print("   - Documents: userProvided (calculés par le crawler)")
                print("   - Requêtes: userProvided (calculés par l'API)")

        else:
            print("\n❌ La mise à jour a échoué :")
            print(f"   Status: {final_task.status}")
            if hasattr(final_task, 'error') and final_task.error:
                print(f"   Erreur: {final_task.error}")

    except MeilisearchTimeoutError:
        print("\n⏱️  Timeout dépassé, vérification manuelle du statut de la tâche...")
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
    import traceback
    traceback.print_exc()
