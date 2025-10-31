import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
import time
import os
import sys

# Ajouter le répertoire racine au path pour l'import de CacheDB
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from dashboard.src.i18n import get_translator
from dashboard.src.state import is_crawler_running
from meilisearchcrawler.cache_db import CacheDB

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

st.title(t("statistics.title"))
st.markdown(t("statistics.subtitle"))

running = is_crawler_running()

@st.cache_data(ttl=10)
def get_cache_stats_from_db():
    """Récupère les statistiques depuis la base de données SQLite."""
    try:
        db_path = os.path.join(BASE_DIR, 'data', 'crawler_cache.db')
        if not os.path.exists(db_path):
            return None
        cache_db = CacheDB(db_path=db_path)
        return cache_db.get_stats()
    except Exception as e:
        st.error(f"Erreur de chargement des statistiques du cache DB: {e}")
        return None

stats = get_cache_stats_from_db()

if stats:
    total_urls = stats.get('total_urls', 0)
    sites = stats.get('sites', {})
    oldest_crawl = stats.get('oldest_crawl')
    newest_crawl = stats.get('newest_crawl')

    st.markdown("### " + t("statistics.cache_overview"))
    col1, col2, col3 = st.columns(3)
    col1.metric(t("statistics.total_urls_in_cache"), f"{total_urls:,}")
    col2.metric(t("statistics.number_of_sites"), len(sites))

    if newest_crawl:
        newest_date = datetime.fromtimestamp(newest_crawl)
        newest_delta = (datetime.now() - newest_date).days
        col3.metric(t("statistics.last_crawl"), f"{newest_date.strftime('%Y-%m-%d %H:%M')}", f"{newest_delta} {t('statistics.days_ago')}")
    else:
        col3.metric(t("statistics.last_crawl"), t("statistics.not_available"))

    st.markdown("### " + t("statistics.site_distribution"))
    if sites:
        sorted_sites = sorted(sites.items(), key=lambda item: item[1], reverse=True)
        df_sites = pd.DataFrame(sorted_sites, columns=[t('statistics.site'), t('statistics.page_count')])
        st.dataframe(df_sites, use_container_width=True, hide_index=True)
    else:
        st.info(t("statistics.no_sites_in_cache"))

    st.markdown("### " + t("statistics.crawl_history"))
    if oldest_crawl and newest_crawl:
        oldest_date_str = datetime.fromtimestamp(oldest_crawl).strftime('%Y-%m-%d')
        newest_date_str = datetime.fromtimestamp(newest_crawl).strftime('%Y-%m-%d')
        st.info(f"{t('statistics.crawl_period')} **{oldest_date_str}** {t('statistics.to')} **{newest_date_str}**.")
    else:
        st.info(t("statistics.no_crawl_history"))

else:
    st.warning(t("statistics.no_cache_found"))

if running:
    st.markdown("---")
    st.caption(t("statistics.auto_refresh_caption_10s"))
    time.sleep(10)
    st.rerun()
