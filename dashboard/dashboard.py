import streamlit as st
import os

from src.state import is_crawler_running
from src.utils import load_cache_stats
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.i18n import get_translator

# =======================
#  Configuration & Page
# =======================
st.set_page_config(
    page_title="MeiliSearchCrawler Dashboard",
    page_icon="🕸️",
    layout="wide"
)

# =======================
#  Internationalization (i18n)
# =======================

AVAILABLE_LANGUAGES = {
    "en": "English",
    "fr": "Français"
}

# Initialiser la langue dans l'état de la session si elle n'existe pas
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"  # Langue par défaut

# Créer la fonction de traduction
t = get_translator(st.session_state.lang)


# =======================
#  Custom CSS
# =======================
st.markdown("""
<style>
    .error-box, .success-box, .warning-box {
        padding: 12px; margin: 8px 0; border-radius: 6px; color: inherit;
    }
    .error-box { background-color: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; }
    .success-box { background-color: rgba(34, 197, 94, 0.1); border-left: 4px solid #22c55e; }
    .warning-box { background-color: rgba(251, 191, 36, 0.1); border-left: 4px solid #fbbf24; }
</style>
""", unsafe_allow_html=True)


# =======================
#  SIDEBAR
# =======================
with st.sidebar:
    st.image("https://raw.githubusercontent.com/meilisearch/meilisearch/main/assets/logo.svg", width=100)
    st.title(t('dashboard_title'))

    # Sélecteur de langue avec drapeaux
    lang_options = {
        "en": "🇬🇧 English",
        "fr": "🇫🇷 Français"
    }
    selected_lang_code = st.selectbox(
        "Language",
        options=list(lang_options.keys()),
        format_func=lambda code: lang_options[code],
        index=list(lang_options.keys()).index(st.session_state.lang)
    )

    if selected_lang_code != st.session_state.lang:
        st.session_state.lang = selected_lang_code
        st.rerun()

    st.markdown("---")

    # Métriques de la barre latérale
    running = is_crawler_running()
    st.metric(t('crawler_status'), f"🟢 {t('active')}" if running else f"🔴 {t('stopped')}")

    meili_client = get_meili_client()
    if meili_client:
        try:
            stats = meili_client.index(INDEX_NAME).get_stats()
            num_docs = getattr(stats, 'number_of_documents', 0)
            st.metric(t('meilisearch_docs'), f"{num_docs:,}")
        except Exception:
            st.metric(t('meilisearch_docs'), "N/A")

    cache_stats = load_cache_stats()
    if cache_stats:
        st.metric(t('cached_urls'), f"{cache_stats['total_urls']:,}")

    st.markdown("---")

# =======================
#  Main Welcome Page
# =======================
st.title(t('welcome_title'))
st.markdown(t('welcome_subtitle'))
st.info(t('welcome_info'), icon="💡")

col1, col2 = st.columns(2)

with col1:
    st.subheader(t('available_pages'))
    st.markdown(f"""
    {t('page_overview')}
    {t('page_controls')}
    {t('page_search')}
    {t('page_stats')}
    {t('page_tree')}
    {t('page_config')}
    {t('page_logs')}
    """)

with col2:
    st.subheader(t('current_status'))
    if running:
        st.success(t('status_running'))
    else:
        st.warning(t('status_stopped'))
