import streamlit as st
import yaml
import time

from dashboard.src.utils import load_sites_config, save_sites_config
from dashboard.src.state import is_crawler_running
from dashboard.src.i18n import get_translator

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.header(t("config.title"))

running = is_crawler_running()
sites_config = load_sites_config()

if sites_config is None:
    st.error(t("config.error_loading"))
else:
    tab1, tab2 = st.tabs([t("config.tab_preview"), t("config.tab_editor")])

    with tab1:
        if 'sites' in sites_config:
            st.subheader(t("config.preview_title").format(count=len(sites_config['sites'])))

            for site in sites_config['sites']:
                with st.expander(f"🌐 {site.get('name', t('config.site_name_undefined'))}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"{t('config.site_type')} `{site.get('type')}`")
                        st.write(f"{t('config.site_url')} {site.get('crawl')}")
                        st.write(f"{t('config.site_max_pages')} {site.get('max_pages', t('config.unlimited'))}")
                    with col2:
                        st.write(f"{t('config.site_depth')} {site.get('depth', t('config.unlimited_depth'))}")
                        st.write(f"{t('config.site_delay')} {site.get('delay', t('config.auto_delay'))}s")
                        if 'lang' in site:
                            st.write(f"{t('config.site_lang')} `{site.get('lang')}`")

                    if site.get('exclude'):
                        st.write(t("config.exclusions"))
                        st.code('\n'.join(site['exclude']), language='text')

    with tab2:
        st.info(t("config.info_edit"))

        try:
            config_text = yaml.dump(sites_config, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception:
            config_text = "Could not format existing configuration."

        edited_config = st.text_area(
            t("config.config_label"),
            value=config_text,
            height=500,
            key="config_editor",
            disabled=running
        )

        if running:
            st.warning(t("config.warning_running"))

        col1, col2, _ = st.columns([1, 1, 4])

        with col1:
            if st.button(t("config.save_button"), type="primary", disabled=running):
                try:
                    new_config = yaml.safe_load(edited_config)
                    if save_sites_config(new_config):
                        st.success(t("config.success_save"))
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(t("config.error_save"))
                except yaml.YAMLError as e:
                    st.error(t("config.error_yaml").format(e=e))

        with col2:
            if st.button(t("config.reset_button"), disabled=running):
                st.rerun()


