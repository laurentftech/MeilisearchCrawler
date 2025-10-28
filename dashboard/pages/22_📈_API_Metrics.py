"""
Streamlit dashboard page to display API metrics from the Prometheus endpoint.
"""

import streamlit as st
import requests
from prometheus_client.parser import text_string_to_metric_families
import pandas as pd

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

    col1.metric(t("api_metrics.meilisearch"), f"{avg_meili_time:.2f} ms")
    col2.metric(t("api_metrics.mediawiki"), f"{avg_wiki_time:.2f} ms")
    col3.metric(t("api_metrics.google_cse"), f"{avg_cse_time:.2f} ms")
    col4.metric(t("api_metrics.reranking"), f"{avg_reranking_time:.2f} ms")

    st.info(t("api_metrics.custom_metrics_info"))

    # --- Crawler Metrics ---
    st.subheader(t("api_metrics.crawler_metrics"))

    col1, col2 = st.columns(2)

    avg_embedding_time = metrics_data.get("crawler_avg_embedding_batch_time_ms", 0)
    avg_indexing_time = metrics_data.get("crawler_avg_indexing_batch_time_ms", 0)

    col1.metric(t("api_metrics.avg_embedding_batch_time"), f"{avg_embedding_time:.2f} ms")
    col2.metric(t("api_metrics.avg_indexing_batch_time"), f"{avg_indexing_time:.2f} ms")


    # --- All Metrics Expander ---
    with st.expander(t("api_metrics.view_all_metrics")):
        df = pd.DataFrame(sorted(metrics_data.items()), columns=[t("api_metrics.metric"), t("api_metrics.value")])
        st.dataframe(df, use_container_width=True)

else:
    st.warning(t("api_metrics.no_metrics_warning"))
