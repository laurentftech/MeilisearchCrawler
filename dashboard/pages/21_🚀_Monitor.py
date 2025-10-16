"""
API Monitor Page
Real-time monitoring of API requests and performance
"""

import streamlit as st
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.i18n import get_translator
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME

# Configuration & i18n
st.set_page_config(
    page_title="API Monitor - Dashboard",
    page_icon="📊",
    layout="wide"
)

if 'lang' not in st.session_state:
    st.session_state.lang = "fr"

t = get_translator(st.session_state.lang)

# Main Page
st.title("📊 API Monitor")
st.markdown("Real-time monitoring of API requests and performance")

# Check if API is enabled
api_enabled = os.getenv("API_ENABLED", "false").lower() == "true"

if not api_enabled:
    st.warning("⚠️ The API is currently disabled.")
    st.info("To enable the API, set `API_ENABLED=true` in your `.env` file.")
    st.stop()

# API Status
api_host = os.getenv("API_HOST", "0.0.0.0")
api_port = os.getenv("API_PORT", "8080")
base_url = f"http://{api_host}:{api_port}"

st.success(f"✅ API is running at {base_url}")

# Metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("API Status", "🟢 Active")

with col2:
    st.metric("Workers", os.getenv("API_WORKERS", "4"))

with col3:
    meili_client = get_meili_client()
    if meili_client:
        try:
            stats = meili_client.index(INDEX_NAME).get_stats()
            num_docs = getattr(stats, 'number_of_documents', 0)
            st.metric("Documents", f"{num_docs:,}")
        except Exception:
            st.metric("Documents", "N/A")
    else:
        st.metric("Documents", "N/A")

with col4:
    reranking = "🟢 Enabled" if os.getenv("RERANKING_ENABLED", "false").lower() == "true" else "🔴 Disabled"
    st.metric("Reranking", reranking)

st.markdown("---")

# Quick Links
st.subheader("🔗 Quick Links")

col1, col2 = st.columns(2)

with col1:
    st.link_button("📖 Swagger UI", f"{base_url}/api/docs", use_container_width=True)

with col2:
    st.link_button("📘 ReDoc", f"{base_url}/api/redoc", use_container_width=True)

st.markdown("---")

# Test API
st.subheader("🧪 Test API")

test_query = st.text_input("Enter a test search query:", "dinosaures")

if st.button("🔍 Test Search"):
    if test_query:
        with st.spinner("Searching..."):
            import requests
            try:
                response = requests.get(
                    f"{base_url}/api/search",
                    params={"q": test_query, "limit": 5},
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    st.success(f"✅ Found {len(data.get('results', []))} results")
                    if data.get('results'):
                        st.json(data)
                    else:
                        st.info("No results found")
                else:
                    st.error(f"❌ Error: {response.status_code}")
                    st.code(response.text)
            except requests.exceptions.ConnectionError:
                st.error(f"❌ Cannot connect to API at {base_url}")
            except Exception as e:
                st.error(f"❌ Error: {e}")
    else:
        st.warning("Please enter a query")
