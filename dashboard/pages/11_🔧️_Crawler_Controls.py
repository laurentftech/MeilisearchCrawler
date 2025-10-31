import streamlit as st
import sys
from pathlib import Path
import time
import subprocess
import sys
import os
from meilisearch_python_sdk.errors import MeilisearchApiError

from dashboard.src.state import start_crawler, stop_crawler, clear_cache, is_crawler_running
from dashboard.src.utils import load_sites_config, load_cache_stats, parse_logs_for_errors, get_meili_client
from dashboard.src.config import CRAWLER_SCRIPT, INDEX_NAME
from dashboard.src.i18n import get_translator

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

st.header(t("controls.title"))

# --- MeiliSearch Index Check ---
client = get_meili_client()
index_exists = False
if client:
    try:
        client.get_index(INDEX_NAME)
        index_exists = True
    except MeilisearchApiError as e:
        if e.code == "index_not_found":
            st.error(f"⚠️ L'index '{INDEX_NAME}' n'existe pas.")
            st.info("Veuillez le créer avant de lancer un crawl.")
            st.page_link("pages/18_☁️_Meilisearch_Server.py", label="Aller à la configuration du serveur", icon="☁️")
        else:
            st.error(f"Erreur de connexion à Meilisearch: {e}")
else:
    st.error("La connexion à Meilisearch n'est pas configurée. Vérifiez votre fichier .env.")

running = is_crawler_running()
controls_disabled = running or not index_exists

# Si le crawler tourne, afficher un message et un lien vers l'aperçu
if running:
    st.info(t("controls.crawler_is_running_info"))
    st.page_link("pages/10_🏠️_Overview.py", label=t("controls.go_to_overview_button"), icon="🏠")

# Vérifier si un provider d'embedding est configuré
embedding_provider = os.getenv("EMBEDDING_PROVIDER", "none").lower()
embeddings_enabled = embedding_provider != "none"

help_text = ""
if not embeddings_enabled:
    help_text = "EMBEDDING_PROVIDER n'est pas configuré ou est sur 'none' dans votre .env"
elif embedding_provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
    help_text = "Le provider Gemini est sélectionné mais GEMINI_API_KEY est manquante."
    embeddings_enabled = False

# Crawl options
col1, col2 = st.columns(2)

with col1:
    st.subheader(t("controls.crawl_options"))

    sites_config = load_sites_config()
    site_names = [t("controls.all_sites")]
    if sites_config and 'sites' in sites_config:
        site_names += [site['name'] for site in sites_config['sites']]

    selected_site = st.selectbox(t("controls.site_to_crawl"), site_names, disabled=controls_disabled)
    force_crawl = st.checkbox(t("controls.force_crawl"), value=False, disabled=controls_disabled)

    # Nouvelle case à cocher pour les embeddings
    generate_embeddings = st.checkbox(
        t("controls.generate_embeddings"),
        value=True,
        disabled=controls_disabled or not embeddings_enabled,
        help=help_text or "Génère un vecteur sémantique pour chaque nouvelle page."
    )

    # Option de cache persistant
    persistent_cache = st.checkbox(
        t("controls.persistent_cache"),
        value=True,
        disabled=controls_disabled,
        help="Exploration en profondeur : ne jamais re-crawler les URLs déjà visitées. Idéal pour découvrir tout le contenu du site sans répétition."
    )

    workers = st.slider(t("controls.workers"), 1, 20, 2, disabled=controls_disabled)

    site_param = None if selected_site == t("controls.all_sites") else selected_site

    if st.button(t("controls.launch_crawl"), disabled=controls_disabled, type="primary", use_container_width=True):
        success = start_crawler(site=site_param, force=force_crawl, workers=workers, embed=generate_embeddings, persistent_cache=persistent_cache)
        if success:
            if site_param:
                st.toast(t('controls.toast_crawler_started_for_site').format(site=site_param), icon="🚀")
            else:
                st.toast(t('controls.toast_crawler_started'), icon="🚀")
            time.sleep(2)
            st.rerun()
        else:
            st.toast(t('controls.toast_crawler_already_running'), icon="⚠️")

with col2:
    st.subheader(t("controls.actions"))

    if st.button(t("controls.stop_crawl"), disabled=not running, type="secondary", use_container_width=True):
        success = stop_crawler()
        if success:
            st.toast(t('controls.toast_stop_signal_sent'), icon="🛑")
            time.sleep(2)
            st.rerun()
        else:
            st.toast(t('controls.toast_crawler_not_running'), icon="ℹ️")

    st.markdown("---")

    if st.button(t("controls.clear_cache"), disabled=controls_disabled, use_container_width=True):
        success = clear_cache()
        if success:
            st.toast(t('controls.toast_cache_cleared'), icon="🗑️")
            time.sleep(1)
            st.rerun()
        else:
            st.toast(t('controls.toast_cache_empty'), icon="ℹ️")

    cache_stats = load_cache_stats()
    if cache_stats and cache_stats['total_urls'] > 0:
        st.info(t("controls.current_cache").format(total_urls=f"{cache_stats['total_urls']:,}", sites=cache_stats['sites']))

    st.markdown("---")

    if st.button(t("controls.show_cache_stats"), use_container_width=True, disabled=running):
        with st.spinner(t("controls.calculating_stats")):
            result = subprocess.run(
                [sys.executable, CRAWLER_SCRIPT, "--stats-only"],
                capture_output=True,
                text=True,
                check=False
            )
            st.code(result.stdout, language='text')

# Recent Errors
st.subheader(t("controls.recent_errors"))
errors = parse_logs_for_errors(50)
if errors:
    for err in reversed(errors[-10:]):
        st.markdown(f'''
        <div class="error-box">
            <small>{err['timestamp']}</small><br>
            <code style="font-size: 0.85em;">{err['message']}</code>
        </div>
        ''', unsafe_allow_html=True)
else:
    st.markdown(f'''
    <div class="success-box">
        {t("controls.no_recent_errors")}
    </div>
    ''', unsafe_allow_html=True)

# Auto-refresh
if running:
    st.markdown("---")
    st.caption(t("controls.auto_refresh_caption"))
    time.sleep(10)
    st.rerun()
