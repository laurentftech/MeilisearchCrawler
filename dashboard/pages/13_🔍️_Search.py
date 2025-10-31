import streamlit as st
import sys
from pathlib import Path
from datetime import datetime
from langdetect import detect, LangDetectException

# This is a hack to make sure the app is launched from the root of the project
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# =======================
#  Vérification de l'accès
# =======================
from dashboard.src.auth import check_authentication
check_authentication()

# Corrected imports for the new SDK and proper pathing
from dashboard.src.meilisearch_client import get_meili_client
from meilisearch_python_sdk.models.search import SearchResults
from meilisearch_python_sdk.errors import MeilisearchApiError
from dashboard.src.config import INDEX_NAME
from dashboard.src.i18n import get_translator

# Initialize translator
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.set_page_config(
    page_title=t("search.page_title"),
    layout="wide"
)

st.title(t("search.title"))
st.markdown(t("search.subtitle"))

# --- Initialization ---
meili_client = get_meili_client()

if not meili_client:
    st.error(t("search.error_meili_connection"))
    st.stop()

try:
    index = meili_client.index(INDEX_NAME)
    stats = index.get_stats()
    if stats.number_of_documents == 0:
        st.warning(t("search.warning_no_documents"))
        st.stop()
except MeilisearchApiError as e:
    if e.code == "index_not_found":
        st.warning(f"⚠️ L'index '{INDEX_NAME}' n'existe pas.")
        st.info("Veuillez le créer pour pouvoir effectuer une recherche.")
        st.page_link("pages/18_☁️_Meilisearch_Server.py", label="Aller à la configuration du serveur", icon="☁️")
        st.stop()
    else:
        st.error(f"{t('search.error_index_access')}: {e}")
        st.stop()
except Exception as e:
    st.error(f"{t('search.error_index_access')}: {e}")
    st.stop()

# --- Search bar and filters ---
with st.form(key="search_form"):
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(t("search.search_box_label"), "", placeholder=t("search.search_box_placeholder"))
    with col2:
        use_hybrid = st.checkbox(t("search.use_hybrid_search"), value=True, help=t("search.hybrid_search_help"))
        semantic_ratio = st.slider(
            t("search.semantic_ratio_label"),
            min_value=0.0,
            max_value=1.0,
            value=0.8,
            step=0.1,
            help=t("search.semantic_ratio_help"),
            disabled=not use_hybrid
        )
    
    submitted = st.form_submit_button(label=t("search.search_button_label"), type="primary")

# --- Search logic ---
if submitted and query:
    with st.spinner(t("search.spinner_searching")):
        # Parameters updated to snake_case for the new SDK
        search_params = {
            "limit": 20,
            "attributes_to_retrieve": ['title', 'url', 'excerpt', 'site', 'images', 'timestamp'],
            "attributes_to_highlight": ['title', 'excerpt'],
            "highlight_pre_tag": "**",
            "highlight_post_tag": "**"
        }

        # --- Smart filters ---
        filters = []

        try:
            query_lang = detect(query)
            if query_lang in ['fr', 'en']:
                filters.append(f"lang = {query_lang}")
                st.caption(f"Search language detected: `{query_lang.upper()}`")
            else:
                filters.append(f"lang = {st.session_state.get('lang', 'fr')}")
        except LangDetectException:
            filters.append(f"lang = {st.session_state.get('lang', 'fr')}")

        keywords = [f'"{word}"' for word in query.split() if len(word) > 2]
        if keywords:
            # Corrected filter to use 'excerpt' instead of 'content'
            filters.append(f"title IN [{', '.join(keywords)}] OR excerpt IN [{', '.join(keywords)}]")

        if filters:
            search_params["filter"] = " AND ".join(filters)

        search_query = query
        if use_hybrid:
            # Hybrid search parameters updated to snake_case
            search_params["hybrid"] = {
                "semantic_ratio": semantic_ratio,
                "embedder": "default"
            }

        try:
            # Use the new SDK which returns a SearchResults object
            response: SearchResults = index.search(search_query, **search_params)
            hits = response.hits
            st.success(t("search.results_summary").format(
                count=len(hits),
                total=response.estimated_total_hits,
                time=response.processing_time_ms
            ))
            st.markdown("---")

            if not hits:
                st.warning(t("search.no_results_found"))
            else:
                for hit in hits:
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        if hit.get('images') and isinstance(hit['images'], list) and len(hit['images']) > 0:
                            st.image(hit['images'][0]['url'], width=150)
                        else:
                            st.image("https://via.placeholder.com/150?text=No+Image", width=150)

                    with col2:
                        title = hit.get('_formatted', {}).get('title', hit.get('title', t('search.no_title')))
                        excerpt = hit.get('_formatted', {}).get('excerpt', hit.get('excerpt', ''))
                        url = hit.get('url', '#')
                        site = hit.get('site', t('search.unknown_site'))
                        timestamp = hit.get('timestamp')

                        st.markdown(f"#### [{title}]({url})")
                        st.markdown(f"<small>{t('search.site')}: **{site}**</small>", unsafe_allow_html=True)
                        if timestamp:
                            date = datetime.fromtimestamp(timestamp)
                            st.markdown(f"<small>{t('search.published_on')}: {date.strftime('%d/%m/%Y')}</small>", unsafe_allow_html=True)

                        st.markdown(excerpt, unsafe_allow_html=True)

                    st.markdown("---")

        except MeilisearchApiError as e:
            st.error(f"{t('search.error_during_search')}: {e}")
        except Exception as e:
            st.error(f"{t('search.error_during_search')}: An unexpected error occurred: {e}")

elif not query:
    st.info(t("search.info_start_searching"))
