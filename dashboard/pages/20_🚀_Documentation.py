"""
API Backend Monitoring Page
Displays real-time statistics and health of the KidSearch API backend
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
import os
import requests
from datetime import datetime
from pathlib import Path

from src.i18n import get_translator

# Initialize translator
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.title("🚀 API Backend Monitor")
st.markdown("*Surveillance du backend de recherche unifiée*")

# API Configuration
API_HOST = os.getenv("API_HOST", "localhost")
API_PORT = os.getenv("API_PORT", "8000")
API_ENABLED = os.getenv("API_ENABLED", "false").lower() == "true"

API_BASE_URL = f"http://{API_HOST}:{API_PORT}/api"


def check_api_health():
    """Check if API is running and healthy."""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        if response.status_code == 200:
            return True, response.json()
        return False, None
    except Exception:
        return False, None


def get_api_stats():
    """Get API statistics."""
    try:
        response = requests.get(f"{API_BASE_URL}/stats", timeout=2)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


# Check API status
api_running, health_data = check_api_health()

# Header status
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    if not API_ENABLED:
        st.warning("⚠️ API backend désactivé dans .env (API_ENABLED=false)")
        st.info("Pour activer: définir `API_ENABLED=true` dans le fichier .env")
        st.stop()
    elif api_running:
        st.success(f"✅ API en ligne - {API_BASE_URL}")
    else:
        st.error(f"❌ API hors ligne - {API_BASE_URL}")
        st.info("Démarrer l'API avec: `python api.py`")

with col2:
    if api_running and health_data:
        st.metric("Version", health_data.get("version", "N/A"))

with col3:
    if api_running:
        st.button("🔄 Rafraîchir", key="refresh_api")

if not api_running:
    st.markdown("---")
    st.subheader("📚 Démarrage rapide")
    st.code("""
# 1. Configurer l'API dans .env
API_ENABLED=true
API_HOST=0.0.0.0
API_PORT=8000

# 2. Configurer Google CSE (optionnel)
GOOGLE_CSE_API_KEY=votre_clé_api
GOOGLE_CSE_ID=votre_search_engine_id

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Démarrer l'API
python api.py
    """, language="bash")
    st.stop()

st.markdown("---")

# Services Health
st.subheader("🏥 État des services")

if health_data:
    services = health_data.get("services", {})

    cols = st.columns(len(services))
    for idx, (service, is_healthy) in enumerate(services.items()):
        with cols[idx]:
            status_icon = "✅" if is_healthy else "❌"
            status_text = "OK" if is_healthy else "Erreur"
            color = "green" if is_healthy else "red"
            st.metric(
                f"{status_icon} {service.title()}",
                status_text,
            )

st.markdown("---")

# API Statistics
st.subheader("📊 Statistiques d'utilisation")

stats = get_api_stats()

if stats:
    # Metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Recherches totales",
            f"{stats.get('total_searches', 0):,}",
        )

    with col2:
        st.metric(
            "Recherches (dernière heure)",
            stats.get('searches_last_hour', 0),
        )

    with col3:
        st.metric(
            "Temps de réponse moyen",
            f"{stats.get('avg_response_time_ms', 0):.0f} ms",
        )

    with col4:
        error_rate = stats.get('error_rate', 0) * 100
        st.metric(
            "Taux d'erreur",
            f"{error_rate:.1f}%",
            delta_color="inverse"
        )

    # CSE Quota
    st.subheader("🔑 Quota Google CSE")
    col1, col2 = st.columns([3, 1])

    with col1:
        quota_used = stats.get('cse_quota_used', 0)
        quota_limit = stats.get('cse_quota_limit', 100)
        quota_pct = (quota_used / quota_limit) * 100 if quota_limit > 0 else 0

        # Progress bar
        st.progress(quota_used / quota_limit if quota_limit > 0 else 0)

    with col2:
        st.metric("Utilisé / Limite", f"{quota_used} / {quota_limit}")

    # Cache hit rate
    cache_hit_rate = stats.get('cache_hit_rate', 0) * 100
    st.metric(
        "Taux de cache CSE",
        f"{cache_hit_rate:.1f}%",
        help="Pourcentage de requêtes CSE servies depuis le cache"
    )

    # Top queries
    if stats.get('top_queries'):
        st.subheader("🔝 Requêtes populaires")
        df_queries = pd.DataFrame(stats['top_queries'])

        if not df_queries.empty:
            # Bar chart
            fig = px.bar(
                df_queries.head(10),
                x='count',
                y='query',
                orientation='h',
                title="Top 10 des recherches",
                text='count',
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                xaxis_title="Nombre de recherches",
                yaxis_title="",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📋 Voir toutes les requêtes"):
                st.dataframe(df_queries, use_container_width=True)

else:
    st.info("Aucune statistique disponible pour le moment")

st.markdown("---")

# API Endpoints
st.subheader("📡 Endpoints disponibles")

endpoints = [
    {
        "Method": "GET",
        "Endpoint": "/api/health",
        "Description": "Vérifier l'état de santé de l'API",
    },
    {
        "Method": "GET",
        "Endpoint": "/api/search",
        "Description": "Recherche unifiée (Meilisearch + CSE + Reranking)",
    },
    {
        "Method": "GET",
        "Endpoint": "/api/stats",
        "Description": "Statistiques d'utilisation de l'API",
    },
    {
        "Method": "POST",
        "Endpoint": "/api/feedback",
        "Description": "Signaler un résultat inapproprié",
    },
]

df_endpoints = pd.DataFrame(endpoints)
st.dataframe(df_endpoints, use_container_width=True)

col1, col2 = st.columns(2)

with col1:
    st.markdown(f"**📖 Documentation Swagger:**")
    st.markdown(f"[{API_BASE_URL}/docs]({API_BASE_URL}/docs)")

with col2:
    st.markdown(f"**📘 Documentation ReDoc:**")
    st.markdown(f"[{API_BASE_URL}/redoc]({API_BASE_URL}/redoc)")

st.markdown("---")

# Test Search
st.subheader("🔍 Tester la recherche")

with st.form("test_search_form"):
    col1, col2 = st.columns([3, 1])

    with col1:
        test_query = st.text_input(
            "Requête de test",
            placeholder="dinosaures",
        )

    with col2:
        test_lang = st.selectbox("Langue", ["fr", "en"])

    col1, col2, col3 = st.columns(3)

    with col1:
        use_cse = st.checkbox("Utiliser Google CSE", value=True)

    with col2:
        use_reranking = st.checkbox("Reranking sémantique", value=True)

    with col3:
        limit = st.number_input("Limite de résultats", 1, 100, 20)

    submit = st.form_submit_button("🚀 Rechercher", type="primary")

if submit and test_query:
    with st.spinner("Recherche en cours..."):
        try:
            params = {
                "q": test_query,
                "lang": test_lang,
                "limit": limit,
                "use_cse": use_cse,
                "use_reranking": use_reranking,
            }

            response = requests.get(f"{API_BASE_URL}/search", params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()

                st.success(f"✅ {len(data['results'])} résultats trouvés en {data['stats']['processing_time_ms']:.0f}ms")

                # Stats
                stats = data['stats']
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("Résultats Meilisearch", stats['meilisearch_results'])

                with col2:
                    st.metric("Résultats Google CSE", stats['cse_results'])

                with col3:
                    reranking_icon = "✅" if stats['reranking_applied'] else "❌"
                    st.metric("Reranking appliqué", reranking_icon)

                # Results
                if data['results']:
                    st.subheader("Résultats")

                    for idx, result in enumerate(data['results'][:5], 1):
                        with st.expander(f"{idx}. {result['title']} ({result['source']})"):
                            st.markdown(f"**URL:** {result['url']}")
                            st.markdown(f"**Score:** {result['score']:.3f}")
                            if result.get('original_score'):
                                st.markdown(f"**Score original:** {result['original_score']:.3f}")
                            st.markdown(f"**Extrait:** {result['excerpt']}")

                    with st.expander("📋 Voir tous les résultats (JSON)"):
                        st.json(data)
                else:
                    st.info("Aucun résultat trouvé")

            else:
                st.error(f"Erreur {response.status_code}: {response.text}")

        except Exception as e:
            st.error(f"Erreur lors de la recherche: {e}")

st.markdown("---")

# Auto-refresh
if api_running:
    if 'pause_api_refresh' not in st.session_state:
        st.session_state.pause_api_refresh = False

    col1, col2 = st.columns([3, 1])
    with col1:
        refresh_rate = st.slider(
            "Rafraîchissement automatique (secondes)",
            5, 60, 30,
            key="api_refresh_slider",
            disabled=st.session_state.pause_api_refresh
        )
    with col2:
        st.write("")
        st.write("")
        if st.session_state.pause_api_refresh:
            if st.button("▶️ Reprendre"):
                st.session_state.pause_api_refresh = False
                st.rerun()
        else:
            if st.button("⏸️ Pause"):
                st.session_state.pause_api_refresh = True
                st.rerun()

    if not st.session_state.pause_api_refresh:
        time.sleep(refresh_rate)
        st.rerun()
