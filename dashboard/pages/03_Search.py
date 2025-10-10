import streamlit as st
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.i18n import get_translator

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.header(t("search.title"))

meili_client = get_meili_client()

if not meili_client:
    st.error(t("search.error_meili_connection"))
else:
    try:
        index = meili_client.index(INDEX_NAME)

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

        available_sites = get_available_sites(index)

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input(
                t("search.search_label"),
                placeholder=t("search.search_placeholder"),
                key="search_query"
            )
        with col2:
            selected_sites = st.multiselect(t("search.filter_by_site"), options=available_sites)

        if query:
            search_params = {
                'limit': 20,
                'attributesToHighlight': ['title', 'excerpt'],
                'highlightPreTag': '<mark>',
                'highlightPostTag': '</mark>'
            }
            if selected_sites:
                filters = ' OR '.join([f'site = "{site}"' for site in selected_sites])
                search_params['filter'] = filters

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
