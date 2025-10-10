import streamlit as st
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME

st.header("🔬 Test de Recherche")

meili_client = get_meili_client()

if not meili_client:
    st.error("❌ Connexion à Meilisearch échouée. Vérifiez votre configuration .env.")
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
                st.warning(f"Impossible de récupérer les sites: {e}")
                return []

        available_sites = get_available_sites(index)

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input(
                "🔍 Rechercher:",
                placeholder="Ex: histoire de France, animaux, sciences...",
                key="search_query"
            )
        with col2:
            selected_sites = st.multiselect("Filtrer par site:", options=available_sites)

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

            with st.spinner("Recherche en cours..."):
                search_results = index.search(query, search_params)

            col1, col2 = st.columns(2)
            col1.metric("Résultats trouvés", search_results.get('estimatedTotalHits', 0))
            col2.metric("Temps de recherche", f"{search_results.get('processingTimeMs', 0)}ms")

            if search_results.get('hits'):
                st.markdown("---")
                for i, hit in enumerate(search_results['hits'], 1):
                    formatted = hit.get('_formatted', {})
                    title = formatted.get('title', hit.get('title', "Titre non disponible"))
                    url = hit.get('url', '#')
                    excerpt = formatted.get('excerpt', hit.get('excerpt', ''))

                    st.markdown(f"""
                    <div style="border-left: 3px solid #667eea; padding-left: 15px; margin-bottom: 20px;">
                        <h4 style="margin-bottom: 5px;">
                            {i}. <a href="{url}" target="_blank">{title}</a>
                        </h4>
                        <small style="color: #666;">
                            <b>Site:</b> {hit.get('site', 'N/A')} | <b>URL:</b> {url[:60]}...
                        </small>
                        <p style="margin-top: 10px;">{excerpt[:300]}...</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("🔍 Aucun résultat trouvé pour cette recherche.")

    except Exception as e:
        st.error(f"❌ Une erreur est survenue lors de la recherche: {e}")
