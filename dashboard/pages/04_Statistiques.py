import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.state import is_crawler_running
import time

st.header("📈 Statistiques Détaillées")

meili_client = get_meili_client()
running = is_crawler_running()

if not meili_client:
    st.error("❌ Connexion à Meilisearch non disponible.")
else:
    try:
        index_ref = meili_client.index(INDEX_NAME)
        stats = index_ref.get_stats()

        try:
            index_info = meili_client.get_index(INDEX_NAME)
            updated_at = index_info.updated_at
        except Exception:
            updated_at = None

        # Main metrics
        col1, col2, col3, col4 = st.columns(4)
        num_docs = getattr(stats, 'number_of_documents', 0)
        col1.metric("📄 Documents", f"{num_docs:,}")

        is_indexing = getattr(stats, 'is_indexing', False)
        col2.metric("⚡ Indexation", "En cours" if is_indexing else "Idle")

        last_update = "Jamais"
        if updated_at and isinstance(updated_at, str):
            try:
                dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                last_update = dt.strftime('%d/%m/%Y %H:%M')
            except ValueError:
                last_update = updated_at
        col3.metric("🕐 Dernière MAJ", last_update)

        try:
            tasks = meili_client.get_tasks({'indexUids': [INDEX_NAME], 'statuses': ['enqueued', 'processing']})
            pending_tasks = tasks.total
        except Exception:
            pending_tasks = "N/A"
        col4.metric("📋 Tâches actives", pending_tasks)

        # Data Volume
        st.markdown("---")
        st.subheader("💾 Volume de Données")
        field_distribution_raw = getattr(stats, 'field_distribution', {})

        # Convertir l'objet FieldDistribution en dictionnaire Python standard
        field_distribution = {}
        if field_distribution_raw:
            try:
                # Si c'est déjà un dict
                if isinstance(field_distribution_raw, dict):
                    field_distribution = field_distribution_raw
                # Si c'est un objet avec __dict__
                elif hasattr(field_distribution_raw, '__dict__'):
                    field_distribution = dict(field_distribution_raw.__dict__)
                # Sinon essayer de le convertir
                else:
                    field_distribution = dict(field_distribution_raw)

                # Nettoyer les valeurs : ne garder que les valeurs entières
                field_distribution = {
                    k: v for k, v in field_distribution.items()
                    if isinstance(v, (int, float)) and not k.startswith('_')
                }
            except Exception as e:
                st.warning(f"Impossible de parser field_distribution: {e}")
                field_distribution = {}

        col1, col2, col3, col4 = st.columns(4)
        if field_distribution and num_docs > 0:
            try:
                total_fields = sum(field_distribution.values())
                avg_fields_per_doc = total_fields / num_docs
            except Exception as e:
                st.error(f"Erreur lors du calcul: {e}")
                total_fields = 0
                avg_fields_per_doc = 0
                # Rough estimate: ~1.5 KB per document on average
                estimated_size_mb = (num_docs * 1.5) / 1024

                col1.metric("💽 Taille estimée", f"{estimated_size_mb:.2f} MB")
                col2.metric("📊 Champs totaux", f"{total_fields:,}")
                col3.metric("📈 Champs/doc (moy)", f"{avg_fields_per_doc:.1f}")
                avg_doc_size_kb = (estimated_size_mb * 1024) / num_docs
                col4.metric("📦 Taille/doc (moy)", f"{avg_doc_size_kb:.2f} KB")
            else:
                col1.metric("💽 Taille estimée", "N/A")
        else:
            col1.metric("💽 Taille estimée", "N/A")

        # Field Distribution
        if field_distribution:
            st.markdown("---")
            st.subheader("📤 Distribution des Champs")
            try:
                df_fields = pd.DataFrame([
                    {'Champ': k, 'Occurrences': v, 'Présence (%)': (v / num_docs) * 100}
                    for k, v in sorted(field_distribution.items(), key=lambda item: item[1], reverse=True)
                ])

                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = px.bar(df_fields.head(10), y='Champ', x='Occurrences', orientation='h',
                                 title='Top 10 des champs les plus utilisés', text='Occurrences',
                                 color='Présence (%)', color_continuous_scale='Viridis')
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    st.dataframe(df_fields.style.format({'Occurrences': '{:,.0f}', 'Présence (%)': '{:.1f}%'}),
                                 use_container_width=True, hide_index=True, height=400)
            except Exception as e:
                st.error(f"Erreur lors de la création du graphique de distribution: {e}")

        # Document Distribution by Site
        st.markdown("---")
        st.subheader("🌐 Distribution des Documents par Site")
        try:
            result = index_ref.search("", {'facets': ['site'], 'limit': 0})
            if 'facetDistribution' in result and 'site' in result['facetDistribution']:
                facets = result['facetDistribution']['site']
                df_facets = pd.DataFrame([{'Site': k, 'Documents': v} for k, v in facets.items()])
                df_facets = df_facets.sort_values('Documents', ascending=False)

                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = px.pie(df_facets, values='Documents', names='Site', title='Répartition par site', hole=0.4)
                    fig.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    st.dataframe(df_facets, use_container_width=True, hide_index=True)

        except Exception as e:
            st.warning(f"Impossible de récupérer la distribution par site: {e}")

    except Exception as e:
        st.error(f"❌ Impossible de récupérer les statistiques de l'index: {e}")

# Auto-refresh
if running:
    st.markdown("---")
    st.caption("💡 Actualisation automatique toutes les 15 secondes...")
    time.sleep(15)
    st.rerun()