import requests
import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

MEILI_URL = os.getenv("MEILI_URL")
API_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")

if not MEILI_URL or not API_KEY:
    print("Erreur: MEILI_URL et MEILI_KEY doivent être définis dans le fichier .env")
    exit(1)

headers = {"Authorization": f"Bearer {API_KEY}"}

print(f"Vérification de l'existence de l'index '{INDEX_NAME}' sur {MEILI_URL}...")

try:
    # 1. Vérifier si l'index existe déjà
    r_get = requests.get(f"{MEILI_URL}/indexes/{INDEX_NAME}", headers=headers, timeout=5)

    if r_get.status_code == 200:
        print(f"✅ L'index '{INDEX_NAME}' existe déjà. Aucune action n'est nécessaire.")
        print("   Détails de l'index:", r_get.json())

    # 2. Si l'index n'existe pas (erreur 404), alors on le crée
    elif r_get.status_code == 404:
        print(f"L'index '{INDEX_NAME}' n'existe pas. Tentative de création...")
        r_post = requests.post(
            f"{MEILI_URL}/indexes",
            headers=headers,
            json={"uid": INDEX_NAME, "primaryKey": "id"},
            timeout=5
        )
        r_post.raise_for_status() # Lève une exception si la création échoue

        print("\nRéponse de Meilisearch :")
        print(f"  Status: {r_post.status_code}")
        print(f"  Contenu: {r_post.json()}")
        print(f"\n✅ L'index '{INDEX_NAME}' a été créé avec succès.")

    # 3. Gérer les autres codes d'erreur possibles
    else:
        print(f"\n❌ Erreur inattendue lors de la vérification de l'index.")
        print(f"   Status: {r_get.status_code}")
        print(f"   Contenu: {r_get.text}")

except requests.exceptions.RequestException as e:
    print(f"\n❌ Erreur de connexion à Meilisearch: {e}")
