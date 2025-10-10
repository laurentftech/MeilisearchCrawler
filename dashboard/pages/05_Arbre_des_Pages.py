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

meili_client = get_meili_client()
running = is_crawler_running()

def load_cache_urls():
    """Charge les URLs depuis le fichier de cache."""
    try:
        with open(CACHE_FILE, 'r') as f:
            return set(json.load(f).keys())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

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
            # On utilise un dictionnaire pour dédupliquer les URLs entre le cache et l'index
            data_map = {}
            data = []
            now = datetime.now()

            # 2. Traiter les documents déjà indexés
            for doc in documents: # type: ignore
                doc_dict = doc if isinstance(doc, dict) else doc.__dict__

                url = doc_dict.get('url', '')
                site = doc_dict.get('site', 'Unknown')
                title = doc_dict.get('title', 'Sans titre')

                # IMPORTANT : On cherche la date d'indexation Meilisearch
                # Cela peut être stocké dans différents champs selon votre crawler
                indexed_at = doc_dict.get('indexed_at') or doc_dict.get('last_modified') or doc_dict.get('timestamp')
                if indexed_at and isinstance(indexed_at, (int, float)):
                    indexed_date = datetime.fromtimestamp(indexed_at)

                # Calculer depuis quand la page est indexée dans Meilisearch
                freshness_days = None
                freshness_category = "Date inconnue"
                freshness_color = "#6b7280"  # Gris par défaut

                if indexed_at:
                    try:
                        if isinstance(indexed_at, str):
                            indexed_date = datetime.fromisoformat(indexed_at.replace('Z', '+00:00'))
                        else:
                            indexed_date = indexed_at

                        # Calculer depuis combien de temps cette page est dans l'index
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
                        pass

                # Parser l'URL pour créer la hiérarchie
                if url:
                    parsed = urlparse(url)
                    path_parts = [p for p in parsed.path.split('/') if p]

                    # Nom de la page
                    if path_parts:
                        page_name = path_parts[-1][:40]
                    else:
                        page_name = "Page d'accueil"

                    data_map[url] = {
                        'site': site,
                        'path_parts': path_parts,
                        'page': page_name,
                        'url': url,
                        'title': title[:100],
                        'freshness_days': freshness_days if freshness_days is not None else 999,
                        'freshness_category': freshness_category,
                        'freshness_color': freshness_color,
                        'indexed_at': indexed_at
                    }

            # 3. Charger les URLs du cache et ajouter celles qui ne sont pas déjà dans l'index
            cached_urls = load_cache_urls()
            for url in cached_urls:
                if url not in data_map:
                    try:
                        parsed = urlparse(url)
                        # Essayer d'extraire le nom du site du filtre si possible
                        site_name = filter_site if filter_site != "Tous les sites" else parsed.netloc

                        # Appliquer le filtre de site
                        if filter_site != "Tous les sites" and site_name not in url:
                            continue

                        path_parts = [p for p in parsed.path.split('/') if p]
                        page_name = path_parts[-1][:40] if path_parts else "Page d'accueil"

                        data_map[url] = {
                            'site': site_name,
                            'path_parts': path_parts,
                            'page': page_name,
                            'url': url,
                            'title': "En attente d'indexation",
                            'freshness_days': 9999, # Valeur très haute pour le tri
                            'freshness_category': "En attente",
                            'freshness_color': "#4b5563", # Gris foncé
                            'indexed_at': None
                        }
                    except Exception:
                        continue # Ignorer les URLs malformées du cache

            data = list(data_map.values())
            
            if not data:
                st.warning("⚠️ Impossible de traiter les données des pages.")
            else:
                df = pd.DataFrame(data)

                # Statistiques
                total_pages = len(df)
                st.markdown("---")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📄 Pages analysées", len(df))
                col2.metric("🌐 Sites", df['site'].nunique())

                avg_freshness = df[df['freshness_days'] < 999]['freshness_days'].mean()
                if pd.notna(avg_freshness):
                    col3.metric("📅 Ancienneté moyenne index", f"{avg_freshness:.1f} jours")
                else:
                    col3.metric("📅 Ancienneté moyenne index", "N/A")

                pending_count = len(df[df['freshness_category'] == "En attente"])
                if pending_count > 0:
                    col4.metric("⏳ Pages en attente", pending_count)

                # Créer la structure hiérarchique pour Plotly
                labels = []
                parents = []
                values = []
                colors = []
                hover_texts = []
                ids = []

                # Compteur pour générer des IDs uniques
                id_counter = 0
                node_map = {}  # Map pour retrouver les nodes par leur chemin

                # Ajouter la racine
                root_id = f"node_{id_counter}"
                id_counter += 1
                labels.append("Toutes les pages")
                parents.append("")
                values.append(total_pages)
                colors.append(30)  # Couleur neutre
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
                                    # Incrémenter la valeur du noeud existant
                                    idx = ids.index(current_parent_id)
                                    values[idx] += 1

                        # Ajouter la page finale
                        page_id = f"node_{id_counter}"
                        id_counter += 1

                        labels.append(row['page'])
                        parents.append(current_parent_id)
                        values.append(1)
                        
                        if row['freshness_category'] == "En attente":
                            colors.append(181) # Couleur spéciale pour "En attente"
                            hover_text = f"<b>{row['url'][:60]}...</b><br>Statut: En attente d'indexation"
                        else:
                            colors.append(row['freshness_days'])
                            hover_text = (
                                f"<b>{row['title']}</b><br>"
                                f"Statut: {row['freshness_category']}<br>"
                                f"Indexé il y a: {row['freshness_days']} jours<br>"
                                f"<a href='{row['url']}'>{row['url'][:50]}...</a>"
                            )
                        hover_texts.append(hover_text)
                        ids.append(page_id)

                # Créer la visualisation
                st.markdown("---")
                st.subheader("🗺️ Carte Hiérarchique - Fraîcheur de l'Indexation")

                st.info("💡 **Code couleur** : Vert = récent | Rouge = ancien | Gris = en attente")

                # Palette de couleurs pour la fraîcheur (inversée pour que vert = récent)
                colorscale = [
                    [0, '#22c55e'],  # Vert (indexé aujourd'hui)
                    [0.05, '#84cc16'],  # Vert clair (< 7j)
                    [0.2, '#eab308'],  # Jaune (< 30j)
                    [0.4, '#f97316'],  # Orange (< 90j)
                    [0.6, '#ef4444'],  # Rouge (> 90j)
                    [0.8, '#991b1b'],  # Rouge foncé (> 180j)
                    [1, '#4b5563']   # Gris pour "En attente"
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
                            cmid=45,  # Centre de l'échelle
                            cmin=0, 
                            cmax=181, # Ajusté pour inclure la couleur "en attente"
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
                    ))
                    fig.update_layout(height=800, margin=dict(t=10, l=10, r=10, b=10))

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
                    ))
                    fig.update_layout(height=800, margin=dict(t=10, l=10, r=10, b=10))

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
                    ))
                    fig.update_layout(height=800, margin=dict(t=10, l=10, r=10, b=10))

                st.plotly_chart(fig, use_container_width=True)

                # Distribution par fraîcheur
                st.markdown("---")
                st.subheader("📊 Distribution par Ancienneté d'Indexation")

                # Ordre des catégories
                category_order = [
                    "Indexé aujourd'hui",
                    "Indexé cette semaine",
                    "Indexé ce mois-ci",
                    "Indexé il y a 1-3 mois",
                    "Indexé il y a > 3 mois",
                    "Date inconnue",
                    "En attente"
                ]

                # Palette de couleurs fixe par catégorie
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

                # Tableau des pages les plus anciennes
                st.markdown("---")
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("⏰ Pages à Ré-indexer (les plus anciennes)")
                    old_pages = df[df['freshness_days'] < 9999].nlargest(10, 'freshness_days')[
                        ['title', 'site', 'freshness_days', 'freshness_category', 'indexed_at']
                    ]
                    if not old_pages.empty:
                        old_pages.columns = ['Titre', 'Site', 'Jours', 'Statut', 'Date indexation']
                        st.dataframe(
                            old_pages.style.format({'Jours': '{:.0f}'}),
                            use_container_width=True,
                            hide_index=True,
                            height=400
                        )
                    else:
                        st.info("Aucune page avec date d'indexation")

                with col2:
                    st.subheader("🆕 Pages Récemment Indexées")
                    recent_pages = df[df['freshness_days'] < 9999].nsmallest(10, 'freshness_days')[
                        ['title', 'site', 'freshness_days', 'freshness_category', 'indexed_at']
                    ]
                    if not recent_pages.empty:
                        recent_pages.columns = ['Titre', 'Site', 'Jours', 'Statut', 'Date indexation']
                        st.dataframe(
                            recent_pages.style.format({'Jours': '{:.0f}'}),
                            use_container_width=True,
                            hide_index=True,
                            height=400
                        )
                    else:
                        st.info("Aucune page avec date d'indexation")

                # Option d'export
                st.markdown("---")
                csv = df[['title', 'url', 'site', 'freshness_days', 'freshness_category', 'indexed_at']].to_csv(
                    index=False)
                st.download_button(
                    label="📥 Exporter les données avec dates d'indexation (CSV)",
                    data=csv,
                    file_name=f"indexation_freshness_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
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