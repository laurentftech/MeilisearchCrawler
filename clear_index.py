import requests
import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

MEILI_URL = os.getenv("MEILI_URL")
API_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch") # Utilise 'kidsearch' par défaut

if not MEILI_URL or not API_KEY:
    print("Erreur: MEILI_URL et MEILI_KEY doivent être définis dans le fichier .env")
    exit(1)

headers = {"Authorization": f"Bearer {API_KEY}"}

print(f"Tentative de vider l'index '{INDEX_NAME}' sur {MEILI_URL}...")

# Demander confirmation
confirm = input("Êtes-vous sûr de vouloir supprimer tous les documents de cet index ? (oui/non): ")

if confirm.lower() == 'oui':
    try:
        r = requests.delete(
            f"{MEILI_URL}/indexes/{INDEX_NAME}/documents",
            headers=headers,
            timeout=5 # Ajout d'un timeout
        )
        r.raise_for_status() # Lève une exception pour les codes d'erreur HTTP

        print("\nRéponse de Meilisearch :")
        print(f"  Status: {r.status_code}")
        print(f"  Contenu: {r.json()}")
        print("\n✅ L'index a été vidé avec succès.")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Erreur de connexion à Meilisearch: {e}")
else:
    print("\nOpération annulée.")
