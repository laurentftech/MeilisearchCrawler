"""
API Documentation Page
Provides documentation and quick start guide for the API
"""

import streamlit as st
import pandas as pd
import os

# Use relative imports within the dashboard package
from dashboard.src.i18n import get_translator

# Initialize translator
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.title("📚 Documentation API")
st.markdown("*Documentation et guide de démarrage pour l'API de recherche unifiée*")

# API Configuration
API_HOST = os.getenv("API_HOST", "localhost")
API_PORT = os.getenv("API_PORT", "8000")
API_ENABLED = os.getenv("API_ENABLED", "false").lower() == "true"
API_BASE_URL = f"http://{API_HOST}:{API_PORT}/api"

st.subheader("🚀 Démarrage rapide")
st.code("""
# 1. Créer un fichier .env à la racine du projet
#    (vous pouvez copier/renommer .env.example)

# 2. Configurer l'API dans .env
API_ENABLED=true
API_HOST=0.0.0.0
API_PORT=8000

# 3. Configurer Meilisearch
MEILI_HTTP_ADDR=http://localhost:7700
MEILI_MASTER_KEY=votre_master_key

# 4. Configurer Google CSE (optionnel)
GOOGLE_CSE_API_KEY=votre_clé_api
GOOGLE_CSE_ID=votre_search_engine_id

# 5. Installer les dépendances
pip install -r requirements.txt

# 6. Démarrer l'API
python api.py
""", language="bash")

st.markdown("---")

st.subheader("📡 Endpoints disponibles")

endpoints = [
    {
        "Method": "GET",
        "Endpoint": "/api/health",
        "Description": "Vérifier l'état de santé de l'API et de ses services.",
    },
    {
        "Method": "GET",
        "Endpoint": "/api/search",
        "Description": "Effectuer une recherche unifiée (Meilisearch + CSE + Reranking).",
    },
    {
        "Method": "GET",
        "Endpoint": "/api/stats",
        "Description": "Obtenir les statistiques d'utilisation de l'API.",
    },
    {
        "Method": "POST",
        "Endpoint": "/api/feedback",
        "Description": "Envoyer un feedback sur un résultat de recherche (ex: inapproprié).",
    },
]

df_endpoints = pd.DataFrame(endpoints)
st.dataframe(df_endpoints, width='stretch', hide_index=True)

st.markdown("---")

st.subheader("🔗 Liens utiles")

if not API_ENABLED:
    st.warning("⚠️ L'API est désactivée. Les liens de documentation peuvent ne pas fonctionner.")
else:
    st.info(f"L'API est configurée pour tourner sur `{API_BASE_URL}`")

col1, col2 = st.columns(2)

with col1:
    st.markdown(f"**📖 Documentation Swagger UI:**")
    st.markdown(f"Permet d'explorer et de tester les endpoints de manière interactive.")
    if API_ENABLED:
        st.link_button("Accéder à Swagger UI", f"{API_BASE_URL}/docs")
    else:
        st.button("Accéder à Swagger UI", disabled=True)


with col2:
    st.markdown(f"**📘 Documentation ReDoc:**")
    st.markdown("Offre une vue plus claire et lisible de la spécification OpenAPI.")
    if API_ENABLED:
        st.link_button("Accéder à ReDoc", f"{API_BASE_URL}/redoc")
    else:
        st.button("Accéder à ReDoc", disabled=True)

st.markdown("---")
st.info("Pour plus de détails sur la configuration et le déploiement, référez-vous au fichier `README.md` du projet.")
