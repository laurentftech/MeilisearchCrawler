import streamlit as st

from src.state import is_crawler_running
from src.utils import load_cache_stats
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME

# =======================
#  Configuration & Page
# =======================
st.set_page_config(
    page_title="MeiliSearchCrawler Dashboard",
    page_icon="🕸️",
    layout="wide"
)

# =======================
#  Custom CSS
# =======================
st.markdown("""
<style>
    /* General metrics */
    .st-emotion-cache-1ht1j8u {
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 0.5rem;
        padding: 1rem;
    }
    /* Sidebar metrics */
    .st-emotion-cache-1gwan2j {
        border-top: 1px solid rgba(255, 255, 255, 0.2);
        padding-top: 1rem;
        margin-top: 1rem;
    }
    /* Custom status boxes */
    .error-box, .success-box, .warning-box {
        padding: 12px; margin: 8px 0; border-radius: 6px; color: inherit;
    }
    .error-box { background-color: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; }
    .error-box small { color: #ef4444; font-weight: 600; }
    .success-box { background-color: rgba(34, 197, 94, 0.1); border-left: 4px solid #22c55e; }
    .warning-box { background-color: rgba(251, 191, 36, 0.1); border-left: 4px solid #fbbf24; }
</style>
""", unsafe_allow_html=True)


# =======================
#  SIDEBAR
# =======================
with st.sidebar:
    st.image("https://raw.githubusercontent.com/meilisearch/meilisearch/main/assets/logo.svg", width=100)
    st.title("Crawler Dashboard")

    st.markdown("---")

    # Crawler Status
    running = is_crawler_running()
    st.metric("Statut du Crawler", "🟢 Actif" if running else "🔴 Arrêté")

    # Meilisearch Info
    meili_client = get_meili_client()
    if meili_client:
        try:
            index_ref = meili_client.index(INDEX_NAME)
            stats = index_ref.get_stats()
            num_docs = getattr(stats, 'number_of_documents', 0)
            st.metric("Documents dans Meilisearch", f"{num_docs:,}")
        except Exception:
            st.metric("Documents dans Meilisearch", "N/A")

    # Cache Info
    cache_stats = load_cache_stats()
    if cache_stats:
        st.metric("URLs en Cache", f"{cache_stats['total_urls']:,}")

    st.markdown("---")
    st.caption("Navigation principale ci-dessus.")

# =======================
#  Main Welcome Page
# =======================

st.title("🕸️ Bienvenue sur le Dashboard MeiliSearchCrawler")
st.markdown("Utilisez la navigation dans la barre latérale pour accéder aux différentes sections.")

st.info("**👈 Sélectionnez une page pour commencer.**", icon="💡")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Pages Disponibles")
    st.markdown("""
    - **🏠 Vue d'ensemble**: Suivez la progression des crawls en temps réel.
    - **🔧 Contrôles**: Démarrez, arrêtez le crawler et gérez le cache.
    - **🔍 Recherche**: Testez des requêtes sur votre index Meilisearch.
    - **📊 Statistiques**: Analysez la distribution des documents et des champs.
    - **⚙️ Configuration**: Modifiez la configuration des sites à crawler.
    - **🪵 Logs**: Consultez les logs détaillés du crawler.
    """)

with col2:
    st.subheader("Statut Actuel")
    if running:
        st.success("**Le crawler est actuellement en cours d'exécution.**\n\nVous pouvez suivre sa progression dans la page `Vue d'ensemble`.")
    else:
        st.warning("**Le crawler est actuellement arrêté.**\n\nAllez dans la page `Contrôles` pour le démarrer.")
