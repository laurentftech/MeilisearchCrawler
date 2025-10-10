import streamlit as st
import time
import subprocess
import sys

from src.state import start_crawler, stop_crawler, clear_cache, is_crawler_running
from src.utils import load_sites_config, load_cache_stats, parse_logs_for_errors
from src.config import CRAWLER_SCRIPT

st.header("⚙️ Contrôles du Crawler")

running = is_crawler_running()

# Crawl options
col1, col2 = st.columns(2)

with col1:
    st.subheader("Options de Crawl")

    sites_config = load_sites_config()
    site_names = ["Tous les sites"]
    if sites_config and 'sites' in sites_config:
        site_names += [site['name'] for site in sites_config['sites']]

    selected_site = st.selectbox("Site à crawler:", site_names, disabled=running)
    force_crawl = st.checkbox("🔄 Force (ignorer le cache)", value=False, disabled=running)
    workers = st.slider("👥 Nombre de workers parallèles", 1, 20, 5, disabled=running)

    site_param = None if selected_site == "Tous les sites" else selected_site

    if st.button("🚀 Lancer le Crawl", disabled=running, type="primary", use_container_width=True):
        start_crawler(site=site_param, force=force_crawl, workers=workers)

with col2:
    st.subheader("Actions")

    if st.button("🛑 Arrêter le Crawl", disabled=not running, type="secondary", use_container_width=True):
        stop_crawler()

    st.markdown("---")

    if st.button("🗑️ Vider le Cache", disabled=running, use_container_width=True):
        clear_cache()

    cache_stats = load_cache_stats()
    if cache_stats:
        st.info(f"📦 Cache actuel: {cache_stats['total_urls']:,} URLs de {cache_stats['sites']} sites")

    st.markdown("---")

    if st.button("📊 Afficher stats cache", use_container_width=True):
        with st.spinner("Calcul des statistiques..."):
            result = subprocess.run(
                [sys.executable, CRAWLER_SCRIPT, "--stats-only"],
                capture_output=True,
                text=True,
                check=False
            )
            st.code(result.stdout, language='text')

# Recent Errors
st.subheader("⚠️ Erreurs Récentes")
errors = parse_logs_for_errors(50)
if errors:
    for err in reversed(errors[-10:]):  # Show 10 most recent
        st.markdown(f"""
        <div class="error-box">
            <small>{err['timestamp']}</small><br>
            <code style="font-size: 0.85em;">{err['message']}</code>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div class="success-box">
        ✅ Aucune erreur récente détectée dans les dernières 100 lignes de log.
    </div>
    """, unsafe_allow_html=True)

# Auto-refresh
if running:
    st.markdown("---")
    st.caption("💡 Actualisation automatique toutes les 10 secondes pendant le crawl...")
    time.sleep(10)
    st.rerun()
