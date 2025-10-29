"""
Visual separator between Crawler and API sections
"""

import streamlit as st
import os

# API Configuration
API_DISPLAY_HOST = os.getenv("API_DISPLAY_HOST") or os.getenv("API_HOST", "localhost")
API_PORT = os.getenv("API_PORT", "8080")

# Build base URL: include port only if not using a reverse proxy (i.e., DISPLAY_HOST == HOST)
if API_DISPLAY_HOST == os.getenv("API_HOST", "localhost"):
    API_BASE_URL = f"http://{API_DISPLAY_HOST}:{API_PORT}/api"
else:
    # Behind reverse proxy: no port in URL
    API_BASE_URL = f"http://{API_DISPLAY_HOST}/api"

st.set_page_config(
    page_title="Section Separator",
    page_icon="━",
    layout="wide"
)

st.title("🚀 API Section")
st.markdown("---")

st.info("👈 Select an API page from the sidebar:")
st.markdown("- **📚 Documentation** : Complete API documentation")
st.markdown("- **📊 Monitor** : Real-time API monitoring")

st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 📖 Interactive Docs")
    st.markdown("Access the FastAPI interactive documentation:")
    st.link_button("Open Swagger UI", f"{API_BASE_URL}/docs", use_container_width=True)
    st.link_button("Open ReDoc", f"{API_BASE_URL}/redoc", use_container_width=True)

with col2:
    st.markdown("### 🔍 Quick Test")
    st.markdown("Test the API directly from your terminal:")
    st.code(f'curl "{API_BASE_URL}/search?q=dinosaures"', language="bash")
