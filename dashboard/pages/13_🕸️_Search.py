import streamlit as st
from datetime import datetime
from langdetect import detect, LangDetectException

from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.i18n import get_translator

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.set_page_config(
    page_title=t("search.page_title"),
    layout="wide"
)

st.title(t("search.title"))
st.markdown(t("search.subtitle"))

# --- Initialisation ---
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
except Exception as e:
    st.error(f"{t('search.error_index_access')}: {e}")
    st.stop()

# --- Barre de recherche et filtres ---
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
    
    # Ajout du bouton de soumission
    submitted = st.form_submit_button(label=t("search.search_button_label"), type="primary")

# --- Logique de recherche ---
if submitted and query:
    with st.spinner(t("search.spinner_searching")):
        search_params = {
            "limit": 20,
            "attributesToRetrieve": ['title', 'url', 'excerpt', 'site', 'images', 'timestamp'],
            "attributesToHighlight": ['title', 'excerpt'],
            "highlightPreTag": "**",
            "highlightPostTag": "**"
        }

        # --- Filtres intelligents ---
        filters = []

        # --- Détection intelligente de la langue de la requête ---
        try:
            # On détecte la langue de la requête de l'utilisateur
            query_lang = detect(query)
            # On s'assure que la langue détectée est l'une de celles que nous gérons
            if query_lang in ['fr', 'en']:
                filters.append(f"lang = {query_lang}")
                st.caption(f"Langue de recherche détectée : `{query_lang.upper()}`")
            else:
                # Si la langue n'est pas gérée, on se rabat sur la langue de l'interface
                filters.append(f"lang = {st.session_state.get('lang', 'fr')}")
        except LangDetectException:
            # Si la détection échoue (requête trop courte), on utilise la langue de l'interface
            filters.append(f"lang = {st.session_state.get('lang', 'fr')}")

        # --- Filtre par mots-clés pour la pertinence ---
        # S'assure que les mots de la requête sont présents, puis la sémantique classe les résultats
        keywords = [f'"{word}"' for word in query.split() if len(word) > 2]
        if keywords:
            filters.append(f"title IN [{', '.join(keywords)}] OR content IN [{', '.join(keywords)}]")

        search_params["filter"] = " AND ".join(filters)

        search_query = query
        if use_hybrid:
            # Pour les versions récentes de Meilisearch, la requête 'q' est au premier niveau,
            # et 'hybrid' ne contient que les options comme 'semanticRatio'.
            # Il faut aussi spécifier l'embedder à utiliser pour la requête.
            search_params["hybrid"] = {
                "semanticRatio": semantic_ratio, "embedder": "query"
            }
            # search_query reste la requête principale

        try:
            response = index.search(search_query, search_params)
            hits = response['hits']
            st.success(t("search.results_summary").format(
                count=len(hits),
                total=response['estimatedTotalHits'],
                time=response['processingTimeMs']
            ))
            st.markdown("---")

            # --- Affichage des résultats ---
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

        except Exception as e:
            st.error(f"{t('search.error_during_search')}: {e}")

elif not query:
    st.info(t("search.info_start_searching"))
