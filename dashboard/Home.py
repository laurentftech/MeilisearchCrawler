import streamlit as st
import os
from dotenv import load_dotenv
import sys
from pathlib import Path

# This is a hack to make sure the app is launched from the root of the project
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Charger les variables d'environnement pour que Streamlit les voie
load_dotenv()

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
from dashboard.src.i18n import get_translator
t = get_translator(st.session_state.lang)

# =======================
#  Vérification de l'accès
# =======================
from dashboard.src.auth import check_authentication
token_info = check_authentication()

# Si on arrive ici, l'utilisateur est authentifié.
# On peut éventuellement utiliser les infos du token plus tard.
# Par exemple, pour afficher le nom de l'utilisateur :
# from jwt import decode
# user_info = decode(token_info['id_token'], options={"verify_signature": False}) 
# st.sidebar.success(f"Connecté en tant que {user_info.get('name')}")


# Import services after auth check
from dashboard.src.state import is_crawler_running
from dashboard.src.utils import load_cache_stats
from dashboard.src.meilisearch_client import get_meili_client
from meilisearchcrawler.config import INDEX_NAME


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

    # Section CRAWLER
    st.markdown(f"### 🕸️ {t('section_crawler')}")

    # Métriques Crawler
    running = is_crawler_running()
    st.metric(t('crawler_status'), f"🟢 {t('active')}" if running else f"🔴 {t('stopped')}")

    cache_stats = load_cache_stats()
    if cache_stats:
        st.metric(t('cached_urls'), f"{cache_stats['total_urls']:,}")

    st.markdown(t('crawler_pages_info'))

    st.markdown("---")

    # Section API
    st.markdown(f"### 🚀 {t('section_api')}")

    # Vérifier si l'API est activée
    api_enabled = os.getenv("API_ENABLED", "false").lower() == "true"
    if api_enabled:
        st.metric(t('api_status'), f"🟢 {t('active')}")
        
        # Construire l'URL de l'API pour l'affichage
        api_display_host = os.getenv("API_DISPLAY_HOST") or os.getenv("DISPLAY_HOST")
        if api_display_host:
            # Si un domaine public est fourni, on utilise https et pas de port
            api_url = f"https://{api_display_host}"
        else:
            # Sinon, on construit une URL locale pour le développement
            api_listen_host = os.getenv("API_HOST", "0.0.0.0")
            display_host = "localhost" if api_listen_host == "0.0.0.0" else api_listen_host
            api_port = os.getenv("API_PORT", "8080")
            api_url = f"http://{display_host}:{api_port}"
        
        st.caption(f"URL: {api_url}")
        # Sauvegarder l'URL dans la session pour les autres pages
        st.session_state.api_url = api_url

    else:
        st.metric(t('api_status'), f"🔴 {t('disabled')}")

    # Métriques Meilisearch
    meili_client = get_meili_client()
    if meili_client:
        try:
            stats = meili_client.index(INDEX_NAME).get_stats()
            num_docs = getattr(stats, 'number_of_documents', 0)
            st.metric(t('meilisearch_docs'), f"{num_docs:,}")
        except Exception:
            st.metric(t('meilisearch_docs'), "N/A")

    st.markdown(t('api_pages_info'))

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
    **{t('section_crawler')}**
    {t('page_overview')}
    {t('page_controls')}
    {t('page_config')}
    {t('page_search')}
    {t('page_stats')}
    {t('page_tree')}
    {t('page_logs')}

    **{t('section_api')}**
    {t('page_embeddings')}
    {t('page_api_documentation')}
    {t('page_api_monitor')}
    {t('page_api_metrics')}
    """)

with col2:
    st.subheader(t('current_status'))
    if running:
        st.success(t('status_running'))
    else:
        st.warning(t('status_stopped'))
