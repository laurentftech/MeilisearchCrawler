import streamlit as st
from meilisearch_python_sdk import Client
from meilisearch_python_sdk.errors import MeilisearchCommunicationError
from .config import MEILI_URL, MEILI_KEY

@st.cache_resource
def get_meili_client():
    """Establishes and caches a connection to the Meilisearch client."""
    if not MEILI_URL or not MEILI_KEY:
        st.error("MEILI_URL and MEILI_KEY must be set in your .env file.")
        return None
    try:
        client = Client(url=MEILI_URL, api_key=MEILI_KEY)
        # Test la connexion en appelant health()
        client.health()
        return client
    except MeilisearchCommunicationError as e:
        st.error(f"Error connecting to Meilisearch: {e}. Please check if the service is running and the URL is correct.")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred while connecting to Meilisearch: {e}")
        return None