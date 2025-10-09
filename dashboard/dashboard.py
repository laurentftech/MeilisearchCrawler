import streamlit as st
import json
import os
import time
from datetime import datetime
import pandas as pd
import plotly.express as px
import subprocess
import signal
import sys
from dotenv import load_dotenv
import meilisearch

# =======================
#  Configuration & Chemins
# =======================
st.set_page_config(page_title="MeiliSearchCrawler Dashboard", layout="wide")

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(DASHBOARD_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
LOG_FILE = os.path.join(DATA_DIR, "logs", "crawler.log")
CACHE_FILE = os.path.join(DATA_DIR, "crawler_cache.json")
PID_FILE = os.path.join(DATA_DIR, "crawler.pid")
CRAWLER_SCRIPT = os.path.join(BASE_DIR, "crawler.py")
SITES_CONFIG_FILE = os.path.join(CONFIG_DIR, "sites.yml")

# =======================
#  Connexion Meilisearch
# =======================
load_dotenv(os.path.join(BASE_DIR, ".env"))
MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")


@st.cache_resource
def get_meili_client():
    if not MEILI_URL or not MEILI_KEY:
        return None
    try:
        client = meilisearch.Client(MEILI_URL, MEILI_KEY)
        # Test de connexion avec health()
        client.health()
        return client
    except Exception as e:
        st.error(f"Erreur de connexion à Meilisearch: {e}")
        return None


meili_client = get_meili_client()


# =======================
#  Fonctions Utilitaires
# =======================
def load_status():
    if not os.path.exists(STATUS_FILE):
        return None
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def load_sites_config():
    if not os.path.exists(SITES_CONFIG_FILE):
        return "Fichier de configuration `config/sites.yml` introuvable."
    with open(SITES_CONFIG_FILE, "r", encoding="utf-8") as f:
        return f.read()


# =======================
#  Fonctions de Contrôle
# =======================
def is_crawler_running():
    if not os.path.exists(PID_FILE):
        return False
    with open(PID_FILE, "r") as f:
        try:
            pid = int(f.read().strip())
        except (ValueError, TypeError):
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def start_crawler():
    if is_crawler_running():
        st.toast("Le crawler est déjà en cours d'exécution.", icon="⚠️")
        return
    try:
        python_executable = sys.executable
        process = subprocess.Popen([python_executable, CRAWLER_SCRIPT])
        with open(PID_FILE, "w") as f:
            f.write(str(process.pid))
        st.toast("Crawler démarré avec succès !", icon="🚀")
        time.sleep(2)
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors du lancement du crawler: {e}")


def stop_crawler():
    if not os.path.exists(PID_FILE):
        st.toast("Le crawler n'est pas en cours d'exécution.", icon="ℹ️")
        return
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        os.remove(PID_FILE)
        st.toast("Le crawler a été arrêté.", icon="🛑")
        time.sleep(2)
        st.rerun()
    except (OSError, ValueError) as e:
        st.error(f"Erreur lors de l'arrêt du crawler: {e}")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


def clear_cache():
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
            st.toast("Cache vidé avec succès !", icon="🗑️")
        except Exception as e:
            st.error(f"Erreur lors de la suppression du cache: {e}")
    else:
        st.toast("Aucun cache à vider.", icon="ℹ️")


# =======================
#  Affichage Principal
# =======================
st.title("🕸️ MeiliSearchCrawler Dashboard")
st.markdown("Suivi des crawls, statistiques et logs en temps réel.")

running = is_crawler_running()

# =======================
#  SECTION: Contrôles
# =======================
st.subheader("⚙️ Contrôles")
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🚀 Lancer le Crawl", disabled=running, use_container_width=True):
        start_crawler()

with col2:
    if st.button("🛑 Arrêter le Crawl", disabled=not running, use_container_width=True):
        stop_crawler()

with col3:
    if st.button("🗑️ Vider le cache", disabled=running, use_container_width=True):
        clear_cache()

# =======================
#  SECTION: Test de Recherche
# =======================
st.subheader("🔬 Test de Recherche")
if not meili_client:
    st.warning("Connexion à Meilisearch échouée. Impossible d'utiliser la recherche.")
else:
    try:
        index = meili_client.index(INDEX_NAME)


        @st.cache_data(ttl=300)
        def get_available_sites():
            try:
                # Utiliser une recherche facetée pour obtenir les sites disponibles
                result = index.search("", {
                    'facets': ['site'],
                    'limit': 0
                })
                if 'facetDistribution' in result and 'site' in result['facetDistribution']:
                    return list(result['facetDistribution']['site'].keys())
                return []
            except Exception as e:
                st.warning(f"Impossible de récupérer les sites: {e}")
                return []


        available_sites = get_available_sites()

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input("Entrez votre recherche ici:", placeholder="Ex: histoire de France")
        with col2:
            selected_sites = st.multiselect("Filtrer par site:", options=available_sites)

        if query:
            search_params = {
                'limit': 10,
                'attributesToHighlight': ['title', 'excerpt'],
                'highlightPreTag': '**',
                'highlightPostTag': '**'
            }
            if selected_sites:
                # Format correct pour les filtres dans l'API récente
                filters = ' OR '.join([f'site = "{site}"' for site in selected_sites])
                search_params['filter'] = filters

            search_results = index.search(query, search_params)

            st.write(
                f"**{search_results['estimatedTotalHits']}** résultats trouvés en {search_results['processingTimeMs']}ms")

            if search_results['hits']:
                for hit in search_results['hits']:
                    formatted = hit.get('_formatted', {})
                    st.markdown(f"""
                    <div style="border-left: 3px solid #ccc; padding-left: 10px; margin-bottom: 20px;">
                        <h5 style="margin-bottom: 5px;">
                            <a href="{hit['url']}" target="_blank">{formatted.get('title', hit['title'])}</a>
                        </h5>
                        <small><b>Site:</b> {hit['site']}</small>
                        <p style="margin-top: 5px;">{formatted.get('excerpt', hit.get('excerpt', ''))}</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Aucun résultat trouvé pour cette recherche.")

    except Exception as e:
        st.error(f"Une erreur est survenue lors de la recherche: {e}")

# =======================
#  SECTION: Statistiques Meilisearch
# =======================
st.subheader("🔍 Statistiques de l'Index Meilisearch")
if meili_client:
    try:
        index_ref = meili_client.index(INDEX_NAME)
        stats = index_ref.get_stats()

        # Récupérer les informations de l'index
        try:
            index_info = meili_client.get_index(INDEX_NAME)
            updated_at = index_info.updated_at
        except:
            updated_at = None

        cols = st.columns(4)

        # Accéder aux attributs de l'objet stats, pas comme un dictionnaire
        num_docs = getattr(stats, 'number_of_documents', getattr(stats, 'numberOfDocuments', 0))
        cols[0].metric("Documents dans l'index", f"{num_docs:,}")

        is_indexing = getattr(stats, 'is_indexing', getattr(stats, 'isIndexing', False))
        is_indexing_status = "✅ Oui" if is_indexing else "☑️ Non"
        cols[1].metric("Indexation en cours ?", is_indexing_status)

        last_update = "Jamais"
        if updated_at:
            if isinstance(updated_at, str):
                # Parser la date si c'est une string
                try:
                    dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    last_update = dt.strftime('%d/%m/%Y %H:%M')
                except:
                    last_update = updated_at
            else:
                last_update = updated_at.strftime('%d/%m/%Y %H:%M')
        cols[2].metric("Dernière Mise à Jour", last_update)

        # Récupérer les tâches récentes
        try:
            tasks_response = meili_client.get_tasks({
                'indexUids': [INDEX_NAME],
                'statuses': ['enqueued', 'processing'],
                'limit': 1000
            })
            # La réponse peut être un objet ou un dict
            if hasattr(tasks_response, 'total'):
                pending_tasks = tasks_response.total
            elif isinstance(tasks_response, dict):
                pending_tasks = tasks_response.get('total', 0)
            else:
                pending_tasks = 0
        except:
            # Fallback si l'API ne supporte pas les paramètres
            try:
                tasks_response = meili_client.get_tasks({'limit': 1000})
                if hasattr(tasks_response, 'results'):
                    results = tasks_response.results
                elif isinstance(tasks_response, dict):
                    results = tasks_response.get('results', [])
                else:
                    results = []

                pending_tasks = sum(1 for t in results
                                    if getattr(t, 'index_uid',
                                               t.get('indexUid') if isinstance(t, dict) else None) == INDEX_NAME and
                                    getattr(t, 'status', t.get('status') if isinstance(t, dict) else None) in [
                                        'enqueued', 'processing'])
            except:
                pending_tasks = 0

        cols[3].metric("Tâches en attente", pending_tasks)

    except Exception as e:
        st.error(f"Impossible de récupérer les stats de l'index '{INDEX_NAME}': {e}")
        st.caption("Vérifiez que l'index existe et que les credentials sont corrects.")

# =======================
#  SECTION: Configuration
# =======================
with st.expander("📝 Afficher la configuration des sites (`config/sites.yml`)"):
    sites_config_content = load_sites_config()
    st.code(sites_config_content, language='yaml')

# =======================
#  SECTION: Statut du Crawler
# =======================
st.subheader("📊 Statut du Crawler")
status = load_status()

if status:
    running_status = "🟢 En cours" if running else "🔴 Arrêté"
    st.metric("Statut Actuel", running_status)

    cols = st.columns(5)
    cols[0].metric("Sites Crawlés", f"{status.get('sites_crawled', 0)} / {status.get('total_sites', 0)}")
    cols[1].metric("Pages Indexées (Crawl)", f"{status.get('pages_indexed', 0):,}")
    cols[2].metric("Erreurs (Crawl)", status.get("errors", 0))
    cols[3].metric("Liens en attente", f"{status.get('queue_length', 0):,}")
    cols[4].metric("Dernière durée", f"{status.get('last_crawl_duration_sec', 0)}s")

    if status.get('total_sites', 0) > 0:
        progress = status.get("sites_crawled", 0) / status["total_sites"]
        st.progress(progress)

    active_site = status.get('active_site')
    if active_site and running:
        st.info(f"**Site actif :** `{active_site}`")
    st.caption(f"Dernière mise à jour : {status.get('timestamp', 'N/A')}")

else:
    st.warning("Aucun statut de crawl trouvé. Lancez un crawl pour générer le fichier `data/status.json`.")

# =======================
#  SECTION: Statistiques par site
# =======================
if status and "stats" in status and status["stats"]:
    st.subheader("🌍 Détail par site")

    df = pd.DataFrame(status["stats"])
    if not df.empty:
        fig = px.bar(df, x="site", y="pages", color="status",
                     title="Pages indexées par site", text="pages")
        st.plotly_chart(fig, use_container_width=True)
    with st.expander("Afficher le tableau brut"):
        st.dataframe(df)

# =======================
#  SECTION: Logs
# =======================
st.subheader("🪵 Logs récents")
log_placeholder = st.empty()


def load_logs(n=50):
    if not os.path.exists(LOG_FILE):
        return ""
    with open(LOG_FILE, "r", encoding='utf-8') as f:
        lines = f.readlines()
    return "".join(lines[-n:])


log_placeholder.code(load_logs(), language='log')

# =======================
#  Auto-refresh
# =======================
st.markdown("---")
if running:
    refresh_rate = st.slider("⏱️ Fréquence d'actualisation (secondes)", 5, 60, 10, key="refresh_slider")
    st.caption("Le dashboard se met à jour automatiquement.")
    time.sleep(refresh_rate)
    st.rerun()