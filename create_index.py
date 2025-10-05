import requests

MEILI_URL = "https://meilisearch.gandulf78.synology.me"
API_KEY = "DW?D%_QBz%=6eJqk?Wsc"
INDEX = "kidsearch"

headers = {"Authorization": f"Bearer {API_KEY}"}

# Crée l'index si non existant
r = requests.post(
    f"{MEILI_URL}/indexes",
    headers=headers,
    json={"uid": INDEX, "primaryKey": "id"}
)
print(r.json())
