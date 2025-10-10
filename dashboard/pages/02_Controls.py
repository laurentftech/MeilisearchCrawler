import streamlit as st
import time
import subprocess
import sys

from src.state import start_crawler, stop_crawler, clear_cache, is_crawler_running
from src.utils import load_sites_config, load_cache_stats, parse_logs_for_errors
from src.config import CRAWLER_SCRIPT
from src.i18n import get_translator

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.header(t("controls.title"))

running = is_crawler_running()

# Crawl options
col1, col2 = st.columns(2)

with col1:
    st.subheader(t("controls.crawl_options"))

    sites_config = load_sites_config()
    site_names = [t("controls.all_sites")]
    if sites_config and 'sites' in sites_config:
        site_names += [site['name'] for site in sites_config['sites']]

    selected_site = st.selectbox(t("controls.site_to_crawl"), site_names, disabled=running)
    force_crawl = st.checkbox(t("controls.force_crawl"), value=False, disabled=running)
    workers = st.slider(t("controls.workers"), 1, 20, 5, disabled=running)

    site_param = None if selected_site == t("controls.all_sites") else selected_site

    if st.button(t("controls.launch_crawl"), disabled=running, type="primary", use_container_width=True):
        success = start_crawler(site=site_param, force=force_crawl, workers=workers)
        if success:
            if site_param:
                st.toast(t('controls.toast_crawler_started_for_site').format(site=site_param), icon="🚀")
            else:
                st.toast(t('controls.toast_crawler_started'), icon="🚀")
            time.sleep(2)
            st.rerun()
        else:
            st.toast(t('controls.toast_crawler_already_running'), icon="⚠️")

with col2:
    st.subheader(t("controls.actions"))

    if st.button(t("controls.stop_crawl"), disabled=not running, type="secondary", use_container_width=True):
        success = stop_crawler()
        if success:
            st.toast(t('controls.toast_stop_signal_sent'), icon="🛑")
            time.sleep(2)
            st.rerun()
        else:
            st.toast(t('controls.toast_crawler_not_running'), icon="ℹ️")

    st.markdown("---")

    if st.button(t("controls.clear_cache"), disabled=running, use_container_width=True):
        success = clear_cache()
        if success:
            st.toast(t('controls.toast_cache_cleared'), icon="🗑️")
            time.sleep(1)
            st.rerun()
        else:
            st.toast(t('controls.toast_cache_empty'), icon="ℹ️")

    cache_stats = load_cache_stats()
    if cache_stats:
        st.info(t("controls.current_cache").format(total_urls=f"{cache_stats['total_urls']:,}", sites=cache_stats['sites']))

    st.markdown("---")

    if st.button(t("controls.show_cache_stats"), use_container_width=True):
        with st.spinner(t("controls.calculating_stats")):
            result = subprocess.run(
                [sys.executable, CRAWLER_SCRIPT, "--stats-only"],
                capture_output=True,
                text=True,
                check=False
            )
            st.code(result.stdout, language='text')

# Recent Errors
st.subheader(t("controls.recent_errors"))
errors = parse_logs_for_errors(50)
if errors:
    for err in reversed(errors[-10:]):
        st.markdown(f'''
        <div class="error-box">
            <small>{err['timestamp']}</small><br>
            <code style="font-size: 0.85em;">{err['message']}</code>
        </div>
        ''', unsafe_allow_html=True)
else:
    st.markdown(f'''
    <div class="success-box">
        {t("controls.no_recent_errors")}
    </div>
    ''', unsafe_allow_html=True)

# Auto-refresh
if running:
    st.markdown("---")
    st.caption(t("controls.auto_refresh_caption"))
    time.sleep(10)
    st.rerun()
