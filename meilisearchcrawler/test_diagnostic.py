"""
Script de diagnostic MeiliSearch pour vérifier la configuration embeddings
"""

import os
import requests
from pathlib import Path
from dotenv import load_dotenv

# Charger le .env depuis la racine du projet
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Alternative : chercher le .env automatiquement
if not os.getenv("MEILI_URL"):
    load_dotenv()  # Cherche .env dans les dossiers parents

MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")

print("="*70)
print("DIAGNOSTIC MEILISEARCH")
print("="*70)

# 1. Vérifier la connexion
print("\n1. Test de connexion...")
try:
    response = requests.get(f"{MEILI_URL}/health")
    if response.status_code == 200:
        print(f"   ✓ MeiliSearch accessible à {MEILI_URL}")
    else:
        print(f"   ✗ Erreur: {response.status_code}")
except Exception as e:
    print(f"   ✗ Impossible de se connecter: {e}")
    exit(1)

# 2. Vérifier la version
print("\n2. Version MeiliSearch...")
try:
    response = requests.get(f"{MEILI_URL}/version")
    version_data = response.json()
    version = version_data.get('pkgVersion', 'inconnue')
    print(f"   Version: {version}")

    # Vérifier si >= 1.3
    major, minor = map(int, version.split('.')[:2])
    if major > 1 or (major == 1 and minor >= 3):
        print(f"   ✓ Version compatible avec les embeddings (≥ v1.3)")
    else:
        print(f"   ✗ Version trop ancienne ! Il faut v1.3 minimum")
        print(f"   → Mettez à jour MeiliSearch sur votre Synology")
except Exception as e:
    print(f"   ✗ Erreur: {e}")

# 3. Vérifier les permissions de la clé
print("\n3. Vérification des permissions...")
headers = {"Authorization": f"Bearer {MEILI_KEY}"}

try:
    # Tester la création d'un index de test
    response = requests.post(
        f"{MEILI_URL}/indexes",
        headers=headers,
        json={"uid": "test_diagnostic", "primaryKey": "id"}
    )

    if response.status_code in [200, 201, 202]:
        print("   ✓ Création d'index: OK")
    elif response.status_code == 403:
        print("   ✗ Erreur 403: La clé n'a pas les permissions")
        print("   → Vérifiez que vous utilisez bien la Master Key")
    else:
        print(f"   ? Statut inattendu: {response.status_code}")

except Exception as e:
    print(f"   ✗ Erreur: {e}")

# 4. Tester la configuration des embedders
print("\n4. Test de configuration des embeddings...")
try:
    response = requests.patch(
        f"{MEILI_URL}/indexes/test_diagnostic/settings/embedders",
        headers=headers,
        json={
            "test_embedder": {
                "source": "userProvided",
                "dimensions": 768
            }
        }
    )

    if response.status_code in [200, 202]:
        print("   ✓ Configuration des embeddings: OK")
        print("   → MeiliSearch supporte bien les embeddings!")
    elif response.status_code == 400:
        error = response.json()
        if "experimental" in str(error).lower():
            print("   ✗ Feature expérimentale non activée!")
            print("   → MeiliSearch doit être lancé avec:")
            print("      --experimental-enable-vector-store")
        else:
            print(f"   ✗ Erreur 400: {error}")
    elif response.status_code == 403:
        print("   ✗ Erreur 403: Permissions insuffisantes")
    else:
        print(f"   ? Statut: {response.status_code}")
        print(f"   Réponse: {response.text}")

except Exception as e:
    print(f"   ✗ Erreur: {e}")

# 5. Nettoyage
print("\n5. Nettoyage...")
try:
    response = requests.delete(
        f"{MEILI_URL}/indexes/test_diagnostic",
        headers=headers
    )
    if response.status_code in [200, 202, 204]:
        print("   ✓ Index de test supprimé")
except Exception as e:
    print(f"   ⚠ Impossible de nettoyer: {e}")

# Résumé
print("\n" + "="*70)
print("RÉSUMÉ")
print("="*70)
print("""
Si tout est ✓ : Vous pouvez utiliser les embeddings!

Si vous voyez "experimental" : 
  → Sur votre Synology, relancez MeiliSearch avec:
     --experimental-enable-vector-store

Si vous voyez "Version trop ancienne" :
  → Mettez à jour MeiliSearch vers v1.3+

Si vous voyez "Permissions insuffisantes" :
  → Vérifiez votre MEILI_MASTER_KEY dans le .env
""")