import streamlit as st
import sys
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
from meilisearch_python_sdk.errors import MeilisearchApiError

from dashboard.src.utils import load_status, load_crawl_history, save_crawl_history, get_meili_client
from dashboard.src.state import start_crawler, is_crawler_running
from dashboard.src.i18n import get_translator
from dashboard.src.config import INDEX_NAME

# This is a hack to make sure the app is launched from the root of the project
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# =======================
#  Vérification de l'accès
# =======================
from dashboard.src.auth import check_authentication, show_user_widget
check_authentication()

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

# Afficher le widget utilisateur avec bouton de déconnexion
show_user_widget(t)

st.title(t("overview.title"))
st.markdown(t("overview.subtitle"))

# --- MeiliSearch Index Check ---
client = get_meili_client()
if client:
    try:
        client.get_index(INDEX_NAME)
    except MeilisearchApiError as e:
        if e.code == "index_not_found":
            st.warning(f"⚠️ L'index '{INDEX_NAME}' n'existe pas.")
            st.info("Veuillez le créer pour visualiser l'aperçu.")
            st.page_link("pages/18_☁️_Meilisearch_Server.py", label="Aller à la configuration du serveur", icon="☁️")
            st.stop()
        else:
            st.error(f"Erreur de connexion à Meilisearch: {e}")
            st.stop()
else:
    st.error("La connexion à Meilisearch n'est pas configurée. Vérifiez votre fichier .env.")
    st.stop()


running = is_crawler_running()
status = load_status()

col1, col2, col3, col4 = st.columns(4)

if status:
    with col1:
        st.metric(
            t("overview.crawled_sites"),
            f"{status.get('sites_crawled', 0)} / {status.get('total_sites', 0)}",
        )
    with col2:
        st.metric(t("overview.indexed_pages"), f"{status.get('pages_indexed', 0):,}")
    with col3:
        st.metric(t("overview.errors"), status.get("errors", 0), delta_color="inverse")
    with col4:
        duration = status.get('last_crawl_duration_sec', 0)
        st.metric(t("overview.last_duration"), f"{duration:.2f}s")

    if status.get('total_sites', 0) > 0:
        progress = status.get("sites_crawled", 0) / status["total_sites"]
        st.progress(progress, text=f"{t('overview.progress')}: {progress * 100:.1f}%")

    active_site = status.get('active_site')
    if active_site and running:
        st.info(f"🔄 {t('overview.crawling_site')} `{active_site}`")

    history = load_crawl_history()
    if len(history) > 1:
        st.subheader(t("overview.crawl_evolution"))
        df_history = pd.DataFrame(history)
        df_history['timestamp'] = pd.to_datetime(df_history['timestamp'])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_history['timestamp'],
            y=df_history['pages_indexed'],
            mode='lines+markers',
            name=t('overview.indexed_pages'),
            line=dict(color='#667eea', width=3)
        ))
        fig.update_layout(
            title=t('overview.chart_indexed_pages_evolution'),
            xaxis_title=t('overview.chart_date'),
            yaxis_title=t('overview.chart_pages'),
            hovermode='x unified',
            height=300
        )
        st.plotly_chart(fig, use_container_width=True)

    if "stats" in status and status["stats"]:
        st.subheader(t("overview.site_performance"))
        df = pd.DataFrame(status["stats"])
        if not df.empty:
            fig = px.bar(
                df, x="site", y="pages", color="status",
                title=t('overview.chart_indexed_pages_by_site'),
                text="pages",
                color_discrete_map={
                    'completed': '#10b981',
                    'in_progress': '#3b82f6',
                    'error': '#f59e0b',
                    'success': '#10b981'
                }
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                xaxis_title=t('overview.chart_site'),
                yaxis_title=t('overview.chart_page_count'),
                showlegend=True,
                legend_title_text=t('overview.chart_status')
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander(t("overview.show_details_table")):
                st.dataframe(df, use_container_width=True)
else:
    st.warning(t("overview.no_status_warning"))
    if st.button(t("overview.launch_first_crawl"), type="primary"):
        start_crawler()

st.markdown("---")
if running:
    if status:
        save_crawl_history(status)

    if 'pause_refresh' not in st.session_state:
        st.session_state.pause_refresh = False

    col1, col2 = st.columns([3, 1])
    with col1:
        refresh_rate = st.slider(t("overview.auto_refresh_label"), 5, 60, 10, key="refresh_slider",
                                 disabled=st.session_state.pause_refresh)
    with col2:
        st.write("")
        st.write("")
        if st.session_state.pause_refresh:
            if st.button(t("overview.resume_button")):
                st.session_state.pause_refresh = False
                st.rerun()
        else:
            if st.button(t("overview.pause_button")):
                st.session_state.pause_refresh = True
                st.rerun()

    if not st.session_state.pause_refresh:
        time.sleep(refresh_rate)
        st.rerun()
else:
    st.caption(t("overview.auto_refresh_caption"))
