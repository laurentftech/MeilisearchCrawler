"""
Streamlit dashboard page to display API metrics from the Prometheus endpoint.
"""

import streamlit as st
import requests
from prometheus_client.parser import text_string_to_metric_families
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from dashboard.src.i18n import get_translator

# Initialize translator
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.set_page_config(
    page_title=t("api_metrics.title"),
    page_icon="📈",
)

st.title(t("api_metrics.title"))
st.markdown(t("api_metrics.subtitle"))

# --- Configuration ---
API_URL = st.session_state.get("api_url", "http://localhost:8080")
METRICS_ENDPOINT = f"{API_URL}/api/metrics"


def fetch_metrics():
    """Fetch metrics from the API endpoint."""
    try:
        headers = {'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
        response = requests.get(METRICS_ENDPOINT, timeout=5, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch metrics from `{METRICS_ENDPOINT}`: {e}")
        return None


def parse_metrics(metrics_text):
    """Parse Prometheus text format into a dictionary of metrics."""
    metrics = {}
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            metric_name = sample.name
            metrics[metric_name] = sample.value
    return metrics


# --- Display Metrics ---

if st.button(t("api_metrics.refresh_button")):
    st.cache_data.clear()

metrics_text = fetch_metrics()

if metrics_text:
    metrics_data = parse_metrics(metrics_text)

    st.header(t("api_metrics.performance_metrics"))

    # --- Main Search Metrics ---
    st.subheader(t("api_metrics.main_search_metrics"))
    col1, col2 = st.columns(2)
    
    avg_search_time = metrics_data.get("avg_search_time_ms", 0)
    total_http_requests = metrics_data.get("http_requests_total", 0)

    col1.metric(t("api_metrics.avg_search_time"), f"{avg_search_time:.2f} ms")
    col2.metric(t("api_metrics.total_http_requests"), f"{total_http_requests:.0f}")

    # --- Detailed Response Times ---
    st.subheader(t("api_metrics.avg_response_times"))
    
    col1, col2, col3, col4 = st.columns(4)
    
    avg_meili_time = metrics_data.get("avg_meilisearch_time_ms", 0)
    avg_wiki_time = metrics_data.get("avg_wiki_time_ms", 0)
    avg_cse_time = metrics_data.get("avg_cse_time_ms", 0)
    avg_reranking_time = metrics_data.get("avg_reranking_time_ms", 0)

    col1.metric(t("api_metrics.meilisearch"), f"{avg_meili_time:.1f} ms")
    col2.metric(t("api_metrics.mediawiki"), f"{avg_wiki_time:.1f} ms")
    col3.metric(t("api_metrics.google_cse"), f"{avg_cse_time:.1f} ms")
    col4.metric(t("api_metrics.reranking"), f"{avg_reranking_time:.2f} ms")

    # --- Timing Breakdown Visualization ---
    st.subheader("⏱️ Répartition des temps de traitement")

    st.info("ℹ️ Les requêtes Meilisearch, MediaWiki et Google CSE sont exécutées **en parallèle** via `asyncio.gather()`. Le reranking est ensuite appliqué de manière séquentielle.")

    # Parallel operations (executed concurrently)
    parallel_operations = {
        "Meilisearch": avg_meili_time,
        "MediaWiki": avg_wiki_time,
        "Google CSE": avg_cse_time,
    }

    # Filter out zero values from parallel ops
    parallel_ops_filtered = {k: v for k, v in parallel_operations.items() if v > 0}

    # Max time of parallel operations (since they run concurrently)
    max_parallel_time = max(parallel_ops_filtered.values()) if parallel_ops_filtered else 0

    # Sequential reranking time
    reranking_time = avg_reranking_time

    # Expected time if operations were truly parallel
    expected_time = max_parallel_time + reranking_time

    # Overhead = actual time - expected time
    overhead_time = max(0, avg_search_time - expected_time)

    if parallel_ops_filtered or reranking_time > 0:
        col1, col2 = st.columns(2)

        with col1:
            # Gantt-style chart showing parallel execution
            fig_gantt = go.Figure()

            # Define colors
            colors = {
                "Meilisearch": "#3498db",  # Blue
                "MediaWiki": "#2ecc71",     # Green
                "Google CSE": "#1abc9c",    # Cyan
                "Reranking": "#e74c3c",     # Red
                "Overhead": "#95a5a6"       # Gray
            }

            y_pos = 0

            # Parallel operations (all start at time 0)
            for name, time_ms in parallel_ops_filtered.items():
                if time_ms > 0:
                    fig_gantt.add_trace(go.Bar(
                        name=name,
                        x=[time_ms],
                        y=[name],
                        orientation='h',
                        marker_color=colors.get(name, "#34495e"),
                        text=f"{time_ms:.1f} ms",
                        textposition='inside',
                        hovertemplate=f"<b>{name}</b> (parallèle)<br>Durée: {time_ms:.1f} ms<extra></extra>",
                        showlegend=False
                    ))

            # Add a visual separator
            y_labels = list(parallel_ops_filtered.keys())

            # Add reranking bar if present (starts after parallel ops)
            if reranking_time > 0:
                y_labels.append("─────────")  # Separator
                y_labels.append("Reranking")

                fig_gantt.add_trace(go.Bar(
                    name="Reranking",
                    x=[reranking_time],
                    y=["Reranking"],
                    orientation='h',
                    marker_color=colors["Reranking"],
                    text=f"{reranking_time:.1f} ms",
                    textposition='inside',
                    hovertemplate=f"<b>Reranking</b> (séquentiel)<br>Durée: {reranking_time:.1f} ms<br>Démarre après les requêtes parallèles<extra></extra>",
                    showlegend=False
                ))

            fig_gantt.update_layout(
                height=max(200, len(y_labels) * 40),
                margin=dict(l=0, r=0, t=30, b=0),
                xaxis_title="Temps (ms)",
                yaxis_title="",
                title="Exécution parallèle des opérations",
                yaxis=dict(categoryorder='array', categoryarray=y_labels[::-1])
            )

            st.plotly_chart(fig_gantt, use_container_width=True)

        with col2:
            # Waterfall chart showing time composition
            fig_waterfall = go.Figure(go.Waterfall(
                name="Temps",
                orientation="v",
                measure=["relative", "relative", "relative", "total"],
                x=["Requêtes<br>parallèles", "Reranking<br>(séquentiel)", "Overhead<br>système", "Temps total"],
                y=[max_parallel_time, reranking_time, overhead_time, avg_search_time],
                text=[f"{max_parallel_time:.1f} ms", f"{reranking_time:.1f} ms",
                      f"{overhead_time:.1f} ms", f"{avg_search_time:.1f} ms"],
                textposition="outside",
                connector={"line": {"color": "rgb(63, 63, 63)"}},
                decreasing={"marker": {"color": "#e74c3c"}},
                increasing={"marker": {"color": "#3498db"}},
                totals={"marker": {"color": "#2ecc71"}}
            ))

            fig_waterfall.update_layout(
                title="Composition du temps total",
                height=350,
                margin=dict(l=0, r=0, t=30, b=0),
                showlegend=False,
                yaxis_title="Temps (ms)"
            )

            st.plotly_chart(fig_waterfall, use_container_width=True)

        # Summary insights
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "⚡ Requêtes parallèles",
                f"{max_parallel_time:.1f} ms",
                help="Temps le plus long parmi les requêtes parallèles (Meilisearch, Wiki, CSE)"
            )

        with col2:
            st.metric(
                "🧮 Reranking",
                f"{reranking_time:.1f} ms",
                help="Temps de calcul du reranking sémantique (séquentiel)"
            )

        with col3:
            st.metric(
                "⚙️ Overhead",
                f"{overhead_time:.1f} ms",
                help="Temps de traitement additionnel (merge, filtrage, etc.)"
            )

        with col4:
            # Calculate efficiency
            if avg_search_time > 0:
                efficiency = (max_parallel_time / avg_search_time) * 100
                st.metric(
                    "📊 Parallélisation",
                    f"{efficiency:.0f}%",
                    help="Pourcentage du temps utilisé par les requêtes parallèles"
                )

        # Show detailed breakdown of parallel operations
        if len(parallel_ops_filtered) > 1:
            st.markdown("**Détail des requêtes parallèles:**")
            cols = st.columns(len(parallel_ops_filtered))
            for idx, (name, time_ms) in enumerate(parallel_ops_filtered.items()):
                with cols[idx]:
                    pct = (time_ms / max_parallel_time * 100) if max_parallel_time > 0 else 0
                    st.metric(
                        name,
                        f"{time_ms:.1f} ms",
                        delta=f"{pct:.0f}% du max" if pct < 100 else "Plus lent"
                    )
    else:
        st.info("Aucune donnée de timing disponible pour le moment.")

    st.info(t("api_metrics.custom_metrics_info"))

    # --- Crawler Metrics ---
    st.subheader(t("api_metrics.crawler_metrics"))

    col1, col2 = st.columns(2)

    avg_embedding_time = metrics_data.get("crawler_avg_embedding_time_per_page_ms", 0)
    avg_indexing_time = metrics_data.get("crawler_avg_indexing_time_per_page_ms", 0)

    col1.metric("Temps moyen embedding par page", f"{avg_embedding_time:.2f} ms")
    col2.metric("Temps moyen indexation par page", f"{avg_indexing_time:.2f} ms")


    # --- All Metrics Expander ---
    with st.expander(t("api_metrics.view_all_metrics")):
        df = pd.DataFrame(sorted(metrics_data.items()), columns=[t("api_metrics.metric"), t("api_metrics.value")])
        st.dataframe(df, use_container_width=True)

else:
    st.warning(t("api_metrics.no_metrics_warning"))
