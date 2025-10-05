import requests

MEILI_URL = "https://meilisearch.gandulf78.synology.me"
API_KEY = "DW?D%_QBz%=6eJqk?Wsc"
INDEX = "kidsearch"

headers = {"Authorization": f"Bearer {API_KEY}"}

# Vide l'index
r = requests.delete(
    f"{MEILI_URL}/indexes/{INDEX}/documents",
    headers=headers,
)

print("Réponse de Meilisearch :")
print(r.status_code)
print(r.json())
