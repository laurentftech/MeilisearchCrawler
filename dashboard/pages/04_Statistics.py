import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import time

from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME
from src.state import is_crawler_running
from src.i18n import get_translator

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.header(t("stats.title"))

meili_client = get_meili_client()
running = is_crawler_running()

if not meili_client:
    st.error(t("stats.error_meili_connection"))
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
        col1.metric(t("stats.documents"), f"{num_docs:,}")

        is_indexing = getattr(stats, 'is_indexing', False)
        col2.metric(t("stats.indexing"), t("stats.indexing_in_progress") if is_indexing else t("stats.indexing_idle"))

        last_update = t("stats.never")
        if updated_at and isinstance(updated_at, str):
            try:
                dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                last_update = dt.strftime('%d/%m/%Y %H:%M')
            except ValueError:
                last_update = updated_at
        col3.metric(t("stats.last_update"), last_update)

        try:
            tasks = meili_client.get_tasks({'indexUids': [INDEX_NAME], 'statuses': ['enqueued', 'processing']})
            pending_tasks = tasks.total
        except Exception:
            pending_tasks = "N/A"
        col4.metric(t("stats.active_tasks"), pending_tasks)

        # Data Volume
        st.markdown("---")
        st.subheader(t("stats.data_volume"))
        col1, col2, col3, col4 = st.columns(4)

        field_distribution = {}
        if hasattr(stats, 'field_distribution') and stats.field_distribution:
            try:
                # Convertir field_distribution en dictionnaire simple
                raw_field_dist = dict(stats.field_distribution)
                # S'assurer que toutes les valeurs sont des entiers
                field_distribution = {}
                for k, v in raw_field_dist.items():
                    if isinstance(v, (int, float)):
                        field_distribution[k] = int(v)
                    elif isinstance(v, dict):
                        # Si c'est un dictionnaire imbriqué, prendre la somme ou ignorer
                        # Selon la structure de MeiliSearch, adapter ici
                        pass
            except (TypeError, AttributeError, ValueError) as e:
                st.warning(f"⚠️ Erreur lors du traitement de field_distribution: {e}")
                field_distribution = {}

        if num_docs > 0:
            estimated_size_mb = (num_docs * 1.5) / 1024  # Rough estimate
            avg_doc_size_kb = 1.5
            col1.metric(t("stats.estimated_size"), f"{estimated_size_mb:.2f} MB")
            col4.metric(t("stats.avg_size_per_doc"), f"{avg_doc_size_kb:.2f} KB")

            if field_distribution:
                try:
                    # Calculer le total uniquement avec des valeurs numériques
                    total_fields = sum(v for v in field_distribution.values() if isinstance(v, (int, float)))
                    if total_fields > 0:
                        avg_fields_per_doc = total_fields / num_docs
                        col2.metric(t("stats.total_fields"), f"{total_fields:,}")
                        col3.metric(t("stats.avg_fields_per_doc"), f"{avg_fields_per_doc:.1f}")
                    else:
                        col2.metric(t("stats.total_fields"), "N/A")
                        col3.metric(t("stats.avg_fields_per_doc"), "N/A")
                except Exception as e:
                    st.warning(f"⚠️ Erreur calcul champs: {e}")
                    col2.metric(t("stats.total_fields"), "N/A")
                    col3.metric(t("stats.avg_fields_per_doc"), "N/A")
            else:
                col2.metric(t("stats.total_fields"), "N/A")
                col3.metric(t("stats.avg_fields_per_doc"), "N/A")
        else:
            col1.metric(t("stats.estimated_size"), "N/A")
            col2.metric(t("stats.total_fields"), "N/A")
            col3.metric(t("stats.avg_fields_per_doc"), "N/A")
            col4.metric(t("stats.avg_size_per_doc"), "N/A")

        # Field Distribution
        if field_distribution and num_docs > 0:
            st.markdown("---")
            st.subheader(t("stats.field_distribution"))

            # Filtrer uniquement les valeurs numériques pour le DataFrame
            valid_fields = {k: v for k, v in field_distribution.items() if isinstance(v, (int, float))}

            if valid_fields:
                df_fields = pd.DataFrame([
                    {
                        t("stats.field"): k,
                        t("stats.occurrences"): int(v),
                        t("stats.presence"): (int(v) / num_docs) * 100
                    }
                    for k, v in sorted(valid_fields.items(), key=lambda item: item[1], reverse=True)
                ])

                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = px.bar(df_fields.head(10), y=t("stats.field"), x=t("stats.occurrences"), orientation='h',
                                 title=t("stats.top_10_fields_chart"), text=t("stats.occurrences"),
                                 color=t("stats.presence"), color_continuous_scale='Viridis')
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    st.dataframe(
                        df_fields.style.format({t("stats.occurrences"): '{:,.0f}', t("stats.presence"): '{:.1f}%'}),
                        use_container_width=True, hide_index=True, height=400)

        # Document Distribution by Site
        st.markdown("---")
        st.subheader(t("stats.doc_distribution_by_site"))
        try:
            result = index_ref.search("", {'facets': ['site'], 'limit': 0})
            if 'facetDistribution' in result and 'site' in result['facetDistribution']:
                facets = result['facetDistribution']['site']
                df_facets = pd.DataFrame([{'Site': k, t("stats.documents"): v} for k, v in facets.items()])
                df_facets = df_facets.sort_values(t("stats.documents"), ascending=False)

                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = px.pie(df_facets, values=t("stats.documents"), names='Site', title=t("stats.pie_chart_title"),
                                 hole=0.4)
                    fig.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    st.dataframe(df_facets, use_container_width=True, hide_index=True)

        except Exception as e:
            st.warning(t("stats.warning_distribution_fetch").format(e=e))

    except Exception as e:
        st.error(t("stats.error_fetch_stats").format(e=e))
        # Afficher les détails de l'erreur en mode debug
        with st.expander("🔍 Détails de l'erreur"):
            st.code(str(e))
            import traceback

            st.code(traceback.format_exc())

# Auto-refresh
if running:
    st.markdown("---")
    st.caption(t("stats.auto_refresh_caption"))
    time.sleep(15)
    st.rerun()