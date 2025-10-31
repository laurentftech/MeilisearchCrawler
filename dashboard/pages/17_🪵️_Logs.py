import streamlit as st
import sys
from pathlib import Path
import os
import time

from dashboard.src.config import LOG_FILE
from dashboard.src.state import is_crawler_running
from dashboard.src.i18n import get_translator

# This is a hack to make sure the app is launched from the root of the project
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# =======================
#  Vérification de l'accès
# =======================
from dashboard.src.auth import check_authentication, show_user_widget
check_authentication()

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

# Afficher le widget utilisateur avec bouton de déconnexion
show_user_widget(t)

st.header(t("logs.title"))

running = is_crawler_running()

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    num_lines = st.slider(t("logs.lines_to_show"), 10, 1000, 200)
with col2:
    filter_level = st.selectbox(t("logs.filter_by_level"), [t("logs.all_levels"), "ERROR", "WARNING", "INFO", "DEBUG"])
with col3:
    st.write("\n")
    if st.button(t("logs.refresh_button")):
        st.rerun()

if not os.path.exists(LOG_FILE):
    st.warning(t("logs.no_log_file"))
else:
    try:
        with open(LOG_FILE, "r", encoding='utf-8') as f:
            lines = f.readlines()

        # Filter and process lines
        filtered_lines = lines
        if filter_level != t("logs.all_levels"):
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
        st.subheader(t("logs.log_stats"))
        col1, col2, col3 = st.columns(3)
        col1.metric(t("logs.total_lines"), len(lines))
        col2.metric(f"🔴 {t('logs.errors')}", sum(1 for l in lines if 'ERROR' in l))
        col3.metric(f"🟡 {t('logs.warnings')}", sum(1 for l in lines if 'WARNING' in l))

    except Exception as e:
        st.error(t("logs.error_reading_logs").format(e=e))

# Auto-refresh
if running:
    st.markdown("---")
    st.caption(t("logs.auto_refresh_caption"))
    time.sleep(5)
    st.rerun()
