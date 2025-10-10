import streamlit as st
import os
import time

from src.config import LOG_FILE
from src.state import is_crawler_running

st.header("🪵 Logs du Crawler")

running = is_crawler_running()

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    num_lines = st.slider("Nombre de lignes à afficher:", 10, 1000, 200)
with col2:
    filter_level = st.selectbox("Filtrer par niveau:", ["Tous", "ERROR", "WARNING", "INFO", "DEBUG"])
with col3:
    st.write("\n")
    if st.button("🔄 Actualiser"):
        st.rerun()

if not os.path.exists(LOG_FILE):
    st.warning("📝 Aucun fichier de log trouvé. Les logs apparaîtront après le premier crawl.")
else:
    try:
        with open(LOG_FILE, "r", encoding='utf-8') as f:
            lines = f.readlines()

        # Filter and process lines
        filtered_lines = lines
        if filter_level != "Tous":
            filtered_lines = [l for l in lines if filter_level in l]

        # Take the last N lines
        log_lines_to_display = filtered_lines[-num_lines:]

        log_content = "".join(log_lines_to_display)

        # Basic syntax highlighting
        log_content = log_content.replace("ERROR", "🔴 ERROR")
        log_content = log_content.replace("WARNING", "🟡 WARNING")
        log_content = log_content.replace("INFO", "🔵 INFO")

        st.code(log_content, language='log', line_numbers=True)

        # Log statistics
        st.subheader("📊 Statistiques des Logs")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total de lignes", len(lines))
        col2.metric("🔴 Erreurs", sum(1 for l in lines if 'ERROR' in l))
        col3.metric("🟡 Warnings", sum(1 for l in lines if 'WARNING' in l))

    except Exception as e:
        st.error(f"❌ Erreur lors de la lecture des logs: {e}")

# Auto-refresh
if running:
    st.markdown("---")
    st.caption("💡 Actualisation automatique toutes les 5 secondes...")
    time.sleep(5)
    st.rerun()
