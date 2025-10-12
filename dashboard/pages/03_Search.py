import streamlit as st
import os
from google import genai

from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.i18n import get_translator


# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.header(t("search.title"))

# --- Gemini Setup ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMBEDDING_MODEL = "text-embedding-004"

@st.cache_resource
def get_gemini_client():
    """Initialise et met en cache le client Gemini."""
    if not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        st.error(f"Erreur d'initialisation de Gemini : {e}")
        return None

gemini_client = get_gemini_client()

meili_client = get_meili_client()

if not meili_client:
    st.error(t("search.error_meili_connection"))
else:
    try:
        index = meili_client.index(INDEX_NAME)

        @st.cache_data(ttl=3600) # On cache pour 1h pour éviter les appels répétés
        def ensure_embedder_is_configured(_index):
            """Vérifie et configure l'embedder 'default' si nécessaire."""
            try:
                settings = _index.get_settings()
                embedders = settings.get('embedders', {})
                if 'default' in embedders:
                    return True # Déjà configuré

                st.toast("Configuration de l'index pour la recherche sémantique...", icon="⚙️")
                task = _index.update_embedders({
                    'default': {
                        'source': 'userProvided',
                        'dimensions': 768
                    }
                })
                _index.wait_for_task(task.task_uid, timeout_in_ms=30000) # Augmentation du timeout à 30s
                return True
            except Exception as e:
                st.error(f"Impossible de configurer l'embedder : {e}")
                return False

        @st.cache_data(ttl=300)
        def get_available_sites(_index):
            """Fetches the list of sites from Meilisearch facets."""
            try:
                result = _index.search("", {'facets': ['site'], 'limit': 0})
                if 'facetDistribution' in result and 'site' in result['facetDistribution']:
                    return list(result['facetDistribution']['site'].keys())
                return []
            except Exception as e:
                st.warning(t("search.warning_sites_fetch").format(e=e))
                return []

        # S'assurer que l'embedder est prêt avant de continuer
        if gemini_client:
            ensure_embedder_is_configured(index)

        available_sites = get_available_sites(index)

        col1, col2 = st.columns([2, 1])
        with col1:
            query = st.text_input(
                t("search.search_label"),
                placeholder=t("search.search_placeholder"),
                key="search_query"
            )

        # Options de recherche
        search_mode = "keyword"
        if gemini_client:
            with col2:
                search_mode_option = st.radio(
                    t("search.search_mode"),
                    [t("search.mode_keyword"), t("search.mode_semantic")],
                    horizontal=True,
                    help=t("search.semantic_mode_help")
                )
                if search_mode_option == t("search.mode_semantic"):
                    search_mode = "semantic"
        
        semantic_ratio = 0.75
        if search_mode == "semantic":
            semantic_ratio = st.slider(
                label=t("search.semantic_ratio_label"),
                min_value=0.0,
                max_value=1.0,
                value=0.75,
                step=0.05,
                help=t("search.semantic_ratio_help")
            )

        selected_sites = st.multiselect(t("search.filter_by_site"), options=available_sites)

        @st.cache_data(show_spinner=t("search.embedding_spinner"))
        def get_query_embedding(query_text):
            """Génère et met en cache l'embedding pour une requête."""
            if not gemini_client:
                return None
            result = gemini_client.models.embed_content(
                model=f"models/{EMBEDDING_MODEL}",
                contents=[query_text]
            )
            return result.embeddings[0].values

        if query:
            vector = None
            if search_mode == "semantic":
                vector = get_query_embedding(query)
                if not vector:
                    st.error(t("search.error_embedding"))

            search_params = {
                'limit': 20,
                'attributesToHighlight': ['title', 'excerpt'],
                'highlightPreTag': '<mark>',
                'highlightPostTag': '</mark>'
            }
            if selected_sites:
                filters = ' OR '.join([f'site = "{site}"' for site in selected_sites])
                search_params['filter'] = filters
            
            if vector:
                search_params['vector'] = vector
                search_params['hybrid'] = {
                    "semanticRatio": semantic_ratio,
                    "embedder": "default"
                }

            with st.spinner(t("search.searching_spinner")):
                search_results = index.search(query, search_params)

            col1, col2 = st.columns(2)
            col1.metric(t("search.results_found"), search_results.get('estimatedTotalHits', 0))
            col2.metric(t("search.search_time"), f"{search_results.get('processingTimeMs', 0)}ms")

            if search_results.get('hits'):
                st.markdown("---")
                for i, hit in enumerate(search_results['hits'], 1):
                    formatted = hit.get('_formatted', {})
                    title = formatted.get('title', hit.get('title', t("search.no_title")))
                    url = hit.get('url', '#')
                    excerpt = formatted.get('excerpt', hit.get('excerpt', ''))

                    st.markdown(f"""
                    <div style="border-left: 3px solid #667eea; padding-left: 15px; margin-bottom: 20px;">
                        <h4 style="margin-bottom: 5px;">
                            {i}. <a href="{url}" target="_blank">{title}</a>
                        </h4>
                        <small style="color: #666;">
                            <b>{t('search.result_site_label')}</b> {hit.get('site', 'N/A')} | <b>{t('search.result_url_label')}</b> {url[:60]}...
                        </small>
                        <p style="margin-top: 10px;">{excerpt[:300]}...</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info(t("search.no_results"))

    except Exception as e:
        st.error(t("search.error_search").format(e=e))
