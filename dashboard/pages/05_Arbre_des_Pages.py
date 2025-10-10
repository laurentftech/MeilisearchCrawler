import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
from urllib.parse import urlparse
import time
import json

from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME, CACHE_FILE
from src.state import is_crawler_running

st.title("🌳 Arbre des Pages")
st.markdown("Visualisez la structure et la fraîcheur de l'indexation Meilisearch de vos pages")

# CSS personnalisé pour améliorer l'apparence des métriques
st.markdown("""
<style>
    /* Supprimer le fond jaune des métriques */
    [data-testid="stMetricValue"] {
        background-color: transparent;
    }

    /* Améliorer l'espacement des métriques */
    [data-testid="metric-container"] {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 1rem;
        border-radius: 0.5rem;
    }

    /* Améliorer les tooltips */
    .stTooltipIcon {
        color: rgba(255, 255, 255, 0.6);
    }
</style>
""", unsafe_allow_html=True)

meili_client = get_meili_client()
running = is_crawler_running()


def load_cache_urls():
    """Charge les URLs depuis le fichier de cache."""
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            # Exclure les clés de métadonnées
            return {url: data for url, data in cache_data.items() if url != '_meta'}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


if not meili_client:
    st.error("❌ Connexion à Meilisearch non disponible.")
else:
    try:
        index_ref = meili_client.index(INDEX_NAME)

        # Récupérer la liste des sites disponibles
        sites_list = ["Tous les sites"]
        with st.spinner("Chargement des sites..."):
            try:
                facet_result = index_ref.search("", {'facets': ['site'], 'limit': 0})
                if 'facetDistribution' in facet_result and 'site' in facet_result['facetDistribution']:
                    sites_list = ["Tous les sites"] + list(facet_result['facetDistribution']['site'].keys())
            except:
                pass

        # Options de visualisation
        col1, col2, col3 = st.columns(3)
        with col1:
            viz_type = st.selectbox(
                "Type de visualisation",
                ["TreeMap", "Sunburst", "Icicle"],
                help="Choisissez le type de représentation hiérarchique"
            )
        with col2:
            max_pages = st.slider(
                "Nombre max de pages",
                min_value=50,
                max_value=1000,
                value=200,
                step=50,
                help="Limiter pour de meilleures performances"
            )
        with col3:
            filter_site = st.selectbox(
                "Filtrer par site",
                sites_list,
                help="Filtrer les résultats par site"
            )

        # Récupérer les documents
        with st.spinner(f"Chargement de {max_pages} pages..."):
            params = {'limit': max_pages}
            if filter_site != "Tous les sites":
                params['filter'] = f'site = "{filter_site}"'

            # 1. Récupérer les documents de Meilisearch
            result = index_ref.get_documents(params)
            documents = result.results if hasattr(result, 'results') else []

        if not documents:
            st.warning("⚠️ Aucune page trouvée dans l'index.")
        else:
            # Préparer les données
            data_map = {}
            now = datetime.now()

            # 2. Traiter les documents déjà indexés
            for doc in documents:
                doc_dict = doc if isinstance(doc, dict) else doc.__dict__

                url = doc_dict.get('url', '')
                site = doc_dict.get('site', 'Unknown')
                title = doc_dict.get('title', 'Sans titre')

                # ✅ FIX PRINCIPAL : Utiliser les champs qui existent réellement
                # Priorité : indexed_at > last_modified > timestamp
                indexed_at = (
                        doc_dict.get('indexed_at') or
                        doc_dict.get('last_modified') or
                        doc_dict.get('timestamp')
                )

                # Gérer aussi last_crawled_at si disponible (pour les nouvelles versions du crawler)
                last_crawled = doc_dict.get('last_crawled_at') or indexed_at
                content_hash = doc_dict.get('content_hash', '')

                # Calculer depuis quand la page est indexée
                freshness_days = None
                freshness_category = "Date inconnue"
                freshness_color = "#6b7280"

                # Calculer depuis le dernier crawl
                last_crawl_days = None
                last_crawl_text = "Jamais crawlée"

                if indexed_at:
                    try:
                        # ✅ Gérer les 2 formats : Unix timestamp (int/float) ET ISO string
                        if isinstance(indexed_at, (int, float)):
                            indexed_date = datetime.fromtimestamp(indexed_at)
                        elif isinstance(indexed_at, str):
                            indexed_date = datetime.fromisoformat(indexed_at.replace('Z', '+00:00'))
                        else:
                            indexed_date = None

                        if indexed_date:
                            freshness_days = (now - indexed_date.replace(tzinfo=None)).days

                            if freshness_days < 1:
                                freshness_category = "Indexé aujourd'hui"
                                freshness_color = "#22c55e"
                            elif freshness_days < 7:
                                freshness_category = "Indexé cette semaine"
                                freshness_color = "#84cc16"
                            elif freshness_days < 30:
                                freshness_category = "Indexé ce mois-ci"
                                freshness_color = "#eab308"
                            elif freshness_days < 90:
                                freshness_category = "Indexé il y a 1-3 mois"
                                freshness_color = "#f97316"
                            else:
                                freshness_category = "Indexé il y a > 3 mois"
                                freshness_color = "#ef4444"
                    except Exception as e:
                        freshness_category = f"Erreur date: {str(e)[:30]}"

                # ✅ NOUVEAU : Calculer depuis le dernier crawl
                if last_crawled:
                    try:
                        if isinstance(last_crawled, (int, float)):
                            crawled_date = datetime.fromtimestamp(last_crawled)
                        elif isinstance(last_crawled, str):
                            crawled_date = datetime.fromisoformat(last_crawled.replace('Z', '+00:00'))
                        else:
                            crawled_date = None

                        if crawled_date:
                            last_crawl_days = (now - crawled_date.replace(tzinfo=None)).days

                            if last_crawl_days < 1:
                                last_crawl_text = "Crawlée aujourd'hui"
                            elif last_crawl_days < 7:
                                last_crawl_text = f"Il y a {last_crawl_days}j"
                            else:
                                last_crawl_text = f"Il y a {last_crawl_days}j"
                    except Exception:
                        pass

                # Parser l'URL pour créer la hiérarchie
                if url:
                    parsed = urlparse(url)
                    path_parts = [p for p in parsed.path.split('/') if p]
                    page_name = path_parts[-1][:40] if path_parts else "Page d'accueil"

                    data_map[url] = {
                        'site': site,
                        'path_parts': path_parts,
                        'page': page_name,
                        'url': url,
                        'title': title[:100],
                        'freshness_days': freshness_days if freshness_days is not None else 999,
                        'freshness_category': freshness_category,
                        'freshness_color': freshness_color,
                        'indexed_at': indexed_at,
                        'last_crawled_at': last_crawled,
                        'last_crawl_days': last_crawl_days if last_crawl_days is not None else 999,
                        'last_crawl_text': last_crawl_text,
                        'content_hash': content_hash,
                        'status': 'indexed'
                    }

            # 3. Charger les URLs du cache et ajouter celles qui ne sont pas encore indexées
            cached_data = load_cache_urls()
            for url, cache_info in cached_data.items():
                if url not in data_map:
                    try:
                        parsed = urlparse(url)
                        # Essayer d'extraire le nom du site
                        site_name = parsed.netloc

                        # Appliquer le filtre de site
                        if filter_site != "Tous les sites" and filter_site.lower() not in url.lower():
                            continue

                        path_parts = [p for p in parsed.path.split('/') if p]
                        page_name = path_parts[-1][:40] if path_parts else "Page d'accueil"

                        # Vérifier si on a une date de crawl dans le cache
                        last_crawl_timestamp = cache_info.get('last_crawl', 0) if isinstance(cache_info, dict) else 0
                        crawl_age_days = 999
                        crawl_text = "Date inconnue"

                        if last_crawl_timestamp:
                            crawl_date = datetime.fromtimestamp(last_crawl_timestamp)
                            crawl_age_days = (now - crawl_date).days
                            if crawl_age_days < 1:
                                crawl_text = "Crawlée aujourd'hui"
                            else:
                                crawl_text = f"Il y a {crawl_age_days}j"

                        data_map[url] = {
                            'site': site_name,
                            'path_parts': path_parts,
                            'page': page_name,
                            'url': url,
                            'title': "En attente d'indexation",
                            'freshness_days': 9999,  # Valeur très haute pour le tri
                            'freshness_category': "En attente",
                            'freshness_color': "#4b5563",
                            'indexed_at': None,
                            'last_crawled_at': last_crawl_timestamp if last_crawl_timestamp else None,
                            'last_crawl_days': crawl_age_days,
                            'last_crawl_text': crawl_text,
                            'content_hash': cache_info.get('content_hash', '') if isinstance(cache_info, dict) else '',
                            'status': 'pending'
                        }
                    except Exception:
                        continue

            data = list(data_map.values())

            if not data:
                st.warning("⚠️ Impossible de traiter les données des pages.")
            else:
                df = pd.DataFrame(data)

                # ✅ STATISTIQUES ENRICHIES
                total_pages = len(df)
                st.markdown("---")
                col1, col2, col3, col4, col5 = st.columns(5)

                col1.metric("📄 Pages analysées", total_pages)
                col2.metric("🌐 Sites", df['site'].nunique())

                avg_freshness = df[df['freshness_days'] < 999]['freshness_days'].mean()
                if pd.notna(avg_freshness):
                    col3.metric("📅 Ancienneté index", f"{avg_freshness:.0f}j")
                else:
                    col3.metric("📅 Ancienneté index", "N/A")

                recent_indexed = len(df[df['freshness_days'] < 7])
                col4.metric("🆕 Indexées (< 7j)", recent_indexed)

                # ✅ NOUVEAU : Pages en attente
                pending_count = len(df[df['status'] == 'pending'])
                if pending_count > 0:
                    col5.metric("⏳ En attente", pending_count)
                else:
                    # Afficher les pages crawlées récemment à la place
                    recent_crawled = len(df[df['last_crawl_days'] < 7])
                    col5.metric("🔍 Crawlées (< 7j)", recent_crawled)

                # ✅ NOUVEAU : Alertes
                st.markdown("---")
                col1, col2, col3 = st.columns(3)

                stale_pages = len(df[df['last_crawl_days'] > 30])
                if stale_pages > 0:
                    col1.metric(
                        "⚠️ À re-crawler",
                        stale_pages,
                        help="Pages non visitées depuis plus de 30 jours"
                    )

                old_indexed = len(df[df['freshness_days'] > 90])
                if old_indexed > 0:
                    col2.metric(
                        "🔴 Indexation ancienne",
                        old_indexed,
                        help="Pages indexées il y a plus de 3 mois"
                    )

                if pending_count > 0:
                    col3.metric(
                        "⏳ File d'attente",
                        pending_count,
                        help="Pages découvertes mais pas encore indexées"
                    )

                # Créer la structure hiérarchique pour Plotly
                labels = []
                parents = []
                values = []
                colors = []
                hover_texts = []
                ids = []

                id_counter = 0
                node_map = {}

                # Ajouter la racine
                root_id = f"node_{id_counter}"
                id_counter += 1
                labels.append("Toutes les pages")
                parents.append("")
                values.append(total_pages)
                colors.append(30)
                hover_texts.append(f"<b>Toutes les pages</b><br>Total: {total_pages} pages")
                ids.append(root_id)
                node_map[""] = root_id

                # Construire la hiérarchie par site
                for site_name in df['site'].unique():
                    site_id = f"node_{id_counter}"
                    id_counter += 1
                    site_data = df[df['site'] == site_name]

                    labels.append(site_name)
                    parents.append(root_id)
                    values.append(len(site_data))
                    colors.append(30)
                    hover_texts.append(f"<b>{site_name}</b><br>Pages: {len(site_data)}")
                    ids.append(site_id)
                    node_map[site_name] = site_id

                    # Ajouter les pages de ce site
                    for _, row in site_data.iterrows():
                        current_parent_id = site_id
                        current_path = site_name

                        # Construire la hiérarchie des dossiers
                        if len(row['path_parts']) > 1:
                            for i, part in enumerate(row['path_parts'][:-1]):
                                current_path = f"{current_path}/{part}"

                                if current_path not in node_map:
                                    folder_id = f"node_{id_counter}"
                                    id_counter += 1

                                    labels.append(part[:30])
                                    parents.append(current_parent_id)
                                    values.append(1)
                                    colors.append(30)
                                    hover_texts.append(f"<b>{part}</b><br>Dossier")
                                    ids.append(folder_id)
                                    node_map[current_path] = folder_id
                                    current_parent_id = folder_id
                                else:
                                    current_parent_id = node_map[current_path]
                                    idx = ids.index(current_parent_id)
                                    values[idx] += 1

                        # Ajouter la page finale
                        page_id = f"node_{id_counter}"
                        id_counter += 1

                        labels.append(row['page'])
                        parents.append(current_parent_id)
                        values.append(1)

                        # ✅ AMÉLIORATION : Hover text enrichi
                        if row['status'] == 'pending':
                            colors.append(181)  # Couleur spéciale pour "En attente"
                            hover_text = (
                                f"<b>{row['url'][:60]}...</b><br>"
                                f"📋 Statut: En attente d'indexation<br>"
                                f"🔄 Crawlée: {row['last_crawl_text']}"
                            )
                        else:
                            colors.append(row['freshness_days'])
                            hover_text = (
                                f"<b>{row['title']}</b><br>"
                                f"📅 Indexé: {row['freshness_category']}<br>"
                                f"🔄 Crawlée: {row['last_crawl_text']}<br>"
                                f"<a href='{row['url']}'>{row['url'][:50]}...</a>"
                            )
                        hover_texts.append(hover_text)
                        ids.append(page_id)

                # Créer la visualisation
                st.markdown("---")
                st.subheader("🗺️ Carte Hiérarchique - Fraîcheur de l'Indexation")

                # Instructions d'utilisation
                with st.expander("ℹ️ Comment naviguer dans la visualisation", expanded=False):
                    st.markdown("""
                    ### 🖱️ Navigation
                    - **Cliquer sur un élément** : Zoomer sur cet élément et ses enfants
                    - **Double-cliquer** : Revenir au niveau précédent (dézoomer)
                    - **Hover (survoler)** : Voir les détails de la page

                    ### 🎨 Code couleur
                    - 🟢 **Vert** : Indexé aujourd'hui ou cette semaine (< 7 jours)
                    - 🟡 **Jaune** : Indexé ce mois-ci (< 30 jours)
                    - 🟠 **Orange** : Indexé il y a 1-3 mois
                    - 🔴 **Rouge** : Indexé il y a plus de 3 mois (à rafraîchir)
                    - ⚫ **Gris foncé** : En attente d'indexation

                    ### 💡 Astuce
                    Pour revenir à la vue d'ensemble, **double-cliquez sur le titre** de la racine ou utilisez le bouton "Reset" en haut à droite du graphique.
                    """)

                st.info("💡 **Cliquez** pour zoomer | **Double-cliquez** pour dézoomer")

                colorscale = [
                    [0, '#22c55e'],  # Vert (indexé aujourd'hui)
                    [0.05, '#84cc16'],  # Vert clair (< 7j)
                    [0.2, '#eab308'],  # Jaune (< 30j)
                    [0.4, '#f97316'],  # Orange (< 90j)
                    [0.6, '#ef4444'],  # Rouge (> 90j)
                    [0.8, '#991b1b'],  # Rouge foncé (> 180j)
                    [1, '#4b5563']  # Gris foncé pour "En attente"
                ]

                if viz_type == "TreeMap":
                    fig = go.Figure(go.Treemap(
                        labels=labels,
                        parents=parents,
                        values=values,
                        ids=ids,
                        marker=dict(
                            colors=colors,
                            colorscale=colorscale,
                            cmid=45,
                            cmin=0,
                            cmax=181,
                            colorbar=dict(
                                title="Jours depuis<br>indexation",
                                thickness=20,
                                len=0.8,
                                tickvals=[0, 7, 30, 90, 180],
                                ticktext=['Aujourd\'hui', '7j', '30j', '90j', '180j+']
                            )
                        ),
                        text=labels,
                        customdata=hover_texts,
                        hovertemplate='%{customdata}<br>Taille: %{value}<extra></extra>',
                        textposition="middle center",
                        branchvalues="total",  # Améliore le calcul des tailles
                    ))
                    fig.update_layout(
                        height=800,
                        margin=dict(t=50, l=10, r=10, b=10),
                        title={
                            'text': "💡 Cliquez pour zoomer | Double-cliquez pour revenir en arrière",
                            'x': 0.5,
                            'xanchor': 'center',
                            'font': {'size': 14, 'color': '#666'}
                        }
                    )

                elif viz_type == "Sunburst":
                    fig = go.Figure(go.Sunburst(
                        labels=labels,
                        parents=parents,
                        values=values,
                        ids=ids,
                        marker=dict(
                            colors=colors,
                            colorscale=colorscale,
                            cmid=45,
                            cmin=0,
                            cmax=181,
                            colorbar=dict(
                                title="Jours depuis<br>indexation",
                                thickness=20,
                                len=0.8,
                                tickvals=[0, 7, 30, 90, 180],
                                ticktext=['Aujourd\'hui', '7j', '30j', '90j', '180j+']
                            )
                        ),
                        customdata=hover_texts,
                        hovertemplate='%{customdata}<br>Taille: %{value}<extra></extra>',
                        branchvalues="total",
                    ))
                    fig.update_layout(
                        height=800,
                        margin=dict(t=50, l=10, r=10, b=10),
                        title={
                            'text': "💡 Cliquez pour zoomer | Double-cliquez au centre pour revenir",
                            'x': 0.5,
                            'xanchor': 'center',
                            'font': {'size': 14, 'color': '#666'}
                        }
                    )

                else:  # Icicle
                    fig = go.Figure(go.Icicle(
                        labels=labels,
                        parents=parents,
                        values=values,
                        ids=ids,
                        marker=dict(
                            colors=colors,
                            colorscale=colorscale,
                            cmid=45,
                            cmin=0,
                            cmax=181,
                            colorbar=dict(
                                title="Jours depuis<br>indexation",
                                thickness=20,
                                len=0.8,
                                tickvals=[0, 7, 30, 90, 180],
                                ticktext=['Aujourd\'hui', '7j', '30j', '90j', '180j+']
                            )
                        ),
                        customdata=hover_texts,
                        hovertemplate='%{customdata}<br>Taille: %{value}<extra></extra>',
                        branchvalues="total",
                    ))
                    fig.update_layout(
                        height=800,
                        margin=dict(t=50, l=10, r=10, b=10),
                        title={
                            'text': "💡 Cliquez pour zoomer | Double-cliquez en haut pour revenir",
                            'x': 0.5,
                            'xanchor': 'center',
                            'font': {'size': 14, 'color': '#666'}
                        }
                    )

                # Configuration commune pour améliorer l'interactivité
                fig.update_layout(
                    hoverlabel=dict(
                        bgcolor="white",
                        font_size=13,
                        font_family="Arial"
                    )
                )

                st.plotly_chart(fig, use_container_width=True, config={
                    'displayModeBar': True,
                    'displaylogo': False,
                    'modeBarButtonsToAdd': ['resetScale2d'],
                    'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                    'toImageButtonOptions': {
                        'format': 'png',
                        'filename': f'arbre_pages_{datetime.now().strftime("%Y%m%d")}',
                        'height': 1000,
                        'width': 1400,
                        'scale': 2
                    }
                })

                # Distribution par fraîcheur
                st.markdown("---")
                st.subheader("📊 Distribution par Ancienneté d'Indexation")

                category_order = [
                    "Indexé aujourd'hui",
                    "Indexé cette semaine",
                    "Indexé ce mois-ci",
                    "Indexé il y a 1-3 mois",
                    "Indexé il y a > 3 mois",
                    "Date inconnue",
                    "En attente"
                ]

                color_map = {
                    "Indexé aujourd'hui": "#22c55e",
                    "Indexé cette semaine": "#84cc16",
                    "Indexé ce mois-ci": "#eab308",
                    "Indexé il y a 1-3 mois": "#f97316",
                    "Indexé il y a > 3 mois": "#ef4444",
                    "Date inconnue": "#6b7280",
                    "En attente": "#4b5563"
                }

                freshness_counts = df['freshness_category'].value_counts()
                freshness_df = pd.DataFrame({
                    'Catégorie': freshness_counts.index,
                    'Nombre': freshness_counts.values
                })

                fig_freshness = px.bar(
                    freshness_df,
                    x='Catégorie',
                    y='Nombre',
                    title='Répartition des pages par ancienneté d\'indexation',
                    color='Catégorie',
                    color_discrete_map=color_map,
                    category_orders={'Catégorie': category_order}
                )
                fig_freshness.update_traces(texttemplate='%{y}', textposition='outside')
                fig_freshness.update_layout(
                    height=400,
                    showlegend=False,
                    xaxis_title="",
                    yaxis_title="Nombre de pages"
                )
                st.plotly_chart(fig_freshness, use_container_width=True)

                # ✅ TABLEAUX ENRICHIS
                st.markdown("---")
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("⏰ Pages à Re-crawler en Priorité")
                    st.caption("Pages anciennes ou non visitées depuis longtemps")

                    # Combiner ancienneté du crawl ET ancienneté d'indexation
                    df['priority_score'] = df['last_crawl_days'] * 0.7 + df['freshness_days'] * 0.3

                    old_pages = df[df['freshness_days'] < 9999].nlargest(10, 'priority_score')[
                        ['title', 'site', 'last_crawl_days', 'freshness_days', 'last_crawl_text', 'status']
                    ]

                    if not old_pages.empty:
                        old_pages.columns = ['Titre', 'Site', 'Jours crawl', 'Jours index', 'Dernière visite', 'Statut']


                        def highlight_priority(row):
                            if row['Jours crawl'] > 90:
                                return ['background-color: rgba(239, 68, 68, 0.1)'] * len(row)
                            elif row['Jours crawl'] > 30:
                                return ['background-color: rgba(251, 191, 36, 0.1)'] * len(row)
                            return [''] * len(row)


                        styled_df = old_pages.style.format({
                            'Jours crawl': '{:.0f}',
                            'Jours index': '{:.0f}',
                        }).apply(highlight_priority, axis=1)

                        st.dataframe(
                            styled_df,
                            use_container_width=True,
                            hide_index=True,
                            height=400
                        )
                    else:
                        st.info("✅ Toutes les pages sont à jour !")

                with col2:
                    st.subheader("🆕 Pages Récemment Crawlées")
                    st.caption("Pages visitées récemment par le crawler")

                    recent_pages = df[df['last_crawl_days'] < 999].nsmallest(10, 'last_crawl_days')[
                        ['title', 'site', 'last_crawl_days', 'freshness_days', 'last_crawl_text', 'status']
                    ]

                    if not recent_pages.empty:
                        recent_pages.columns = ['Titre', 'Site', 'Jours crawl', 'Jours index', 'Dernière visite',
                                                'Statut']


                        def highlight_fresh(row):
                            if row['Jours crawl'] < 1:
                                return ['background-color: rgba(34, 197, 94, 0.1)'] * len(row)
                            elif row['Jours crawl'] < 7:
                                return ['background-color: rgba(132, 204, 22, 0.1)'] * len(row)
                            return [''] * len(row)


                        styled_df = recent_pages.style.format({
                            'Jours crawl': '{:.0f}',
                            'Jours index': '{:.0f}',
                        }).apply(highlight_fresh, axis=1)

                        st.dataframe(
                            styled_df,
                            use_container_width=True,
                            hide_index=True,
                            height=400
                        )
                    else:
                        st.info("Aucune page crawlée récemment")

                # Option d'export
                st.markdown("---")
                csv = df[['title', 'url', 'site', 'freshness_days', 'freshness_category', 'last_crawl_text', 'status',
                          'indexed_at']].to_csv(
                    index=False)
                st.download_button(
                    label="📥 Exporter les données complètes (CSV)",
                    data=csv,
                    file_name=f"indexation_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )

    except Exception as e:
        st.error(f"❌ Erreur lors de la création de la visualisation: {e}")
        st.exception(e)

# Auto-refresh
if running:
    st.markdown("---")
    st.caption("💡 Actualisation automatique toutes les 30 secondes...")
    time.sleep(30)
    st.rerun()