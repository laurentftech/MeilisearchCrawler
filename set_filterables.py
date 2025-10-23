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

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

print(f"🔍 Configuration de l'attribut filterable 'lang' sur l'index '{INDEX_NAME}'...")

try:
    # 1. Récupérer les settings actuels
    r_get = requests.get(f"{MEILI_URL}/indexes/{INDEX_NAME}/settings", headers=headers, timeout=5)

    if r_get.status_code != 200:
        print(f"❌ Impossible de récupérer les settings de l'index.")
        print(f"   Status: {r_get.status_code}")
        print(f"   Contenu: {r_get.text}")
        exit(1)

    settings = r_get.json()
    existing_filterables = settings.get("filterableAttributes", [])

    print(f"⚙️ FilterableAttributes actuels: {existing_filterables}")

    # 2. Vérifier si "lang" est déjà filterable
    if "lang" in existing_filterables:
        print(f"✅ L'attribut 'lang' est déjà configuré comme filterable.")
    else:
        print(f"➡️ Ajout de 'lang' aux filterableAttributes...")

        new_filterables = list(set(existing_filterables + ["lang"]))

        r_update = requests.patch(
            f"{MEILI_URL}/indexes/{INDEX_NAME}/settings",
            headers=headers,
            json={"filterableAttributes": new_filterables},
            timeout=5
        )

        r_update.raise_for_status()

        print("\n📨 Réponse de Meilisearch :")
        print(f"  Status: {r_update.status_code}")
        print(f"  Contenu: {r_update.json()}")
        print(f"\n✅ L'attribut 'lang' est maintenant filterable !")

except requests.exceptions.RequestException as e:
    print(f"\n❌ Erreur de connexion à Meilisearch: {e}")
