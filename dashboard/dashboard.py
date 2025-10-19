import streamlit as st
import os
import hmac  # Pour la comparaison sécurisée de mots de passe
from dotenv import load_dotenv

from src.state import is_crawler_running
from src.utils import load_cache_stats
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.i18n import get_translator

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
t = get_translator(st.session_state.lang)

# =======================
#  Portail d'Authentification
# =======================

def check_password():
    """Retourne `True` si l'utilisateur a entré le bon mot de passe."""

    def password_entered():
        """Vérifie si le mot de passe entré par l'utilisateur est correct."""
        try:
            # Comparaison sécurisée pour éviter les attaques temporelles
            password_correct = hmac.compare_digest(
                st.session_state["password"], os.getenv("DASHBOARD_PASSWORD")
            )
        except (KeyError, AttributeError):
            password_correct = False

        st.session_state["password_correct"] = password_correct
        if password_correct:
            del st.session_state["password"]  # Supprimer le mdp de la session

    if st.session_state.get("password_correct", False):
        return True

    # Afficher le formulaire de connexion
    st.title(f"🔒 {t('auth_required')}")
    st.text_input(
        t('password_label'), type="password", on_change=password_entered, key="password"
    )
    if "password_correct" in st.session_state and not st.session_state.password_correct:
        st.error(f"😕 {t('incorrect_password')}")
    return False

def run_security_check():
    """
    Exécute la vérification de sécurité.
    Retourne `False` si l'accès doit être bloqué, `True` sinon.
    """
    # Si DASHBOARD_PASSWORD est défini dans les variables d'environnement, on active la protection.
    dashboard_password = os.getenv("DASHBOARD_PASSWORD")
    if dashboard_password:
        return check_password()

    # Sinon, l'accès est libre.
    return True

# =======================
#  Vérification de l'accès
# =======================
if not run_security_check():
    st.stop()  # Arrête l'exécution si l'authentification échoue


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
    {t('page_overview')}
    {t('page_controls')}
    {t('page_search')}
    {t('page_stats')}
    {t('page_tree')}
    {t('page_embeddings')}
    {t('page_config')}
    {t('page_logs')}
    """)

with col2:
    st.subheader(t('current_status'))
    if running:
        st.success(t('status_running'))
    else:
        st.warning(t('status_stopped'))
