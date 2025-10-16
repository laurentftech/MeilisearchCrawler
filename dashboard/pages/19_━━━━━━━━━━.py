"""
Visual separator between Crawler and API sections
"""

import streamlit as st

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
    st.link_button("Open Swagger UI", "http://localhost:8080/api/docs", use_container_width=True)
    st.link_button("Open ReDoc", "http://localhost:8080/api/redoc", use_container_width=True)

with col2:
    st.markdown("### 🔍 Quick Test")
    st.markdown("Test the API directly from your terminal:")
    st.code('curl "http://localhost:8080/api/search?q=dinosaures"', language="bash")
