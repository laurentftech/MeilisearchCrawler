import streamlit as st
import json
import os
import time
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import subprocess
import signal
import sys
from dotenv import load_dotenv
import meilisearch
import yaml
import re
from collections import defaultdict

# =======================
#  Configuration & Chemins
# =======================
st.set_page_config(page_title="MeiliSearchCrawler Dashboard", layout="wide", page_icon="🕸️")

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
HISTORY_FILE = os.path.join(DATA_DIR, "crawl_history.json")

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
        return None
    try:
        with open(SITES_CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def save_sites_config(config):
    try:
        with open(SITES_CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde: {e}")
        return False


def load_cache_stats():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
            return {
                'total_urls': len(cache),
                'sites': len(set(url.split('/')[2] for url in cache.keys() if '://' in url))
            }
    except:
        return None


def parse_logs_for_errors(n=100):
    """Extrait les erreurs des logs"""
    if not os.path.exists(LOG_FILE):
        return []

    errors = []
    try:
        with open(LOG_FILE, "r", encoding='utf-8') as f:
            lines = f.readlines()[-n:]

        for line in lines:
            if 'ERROR' in line or 'Exception' in line:
                match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                timestamp = match.group(1) if match else "N/A"
                errors.append({'timestamp': timestamp, 'message': line.strip()})
    except:
        pass

    return errors


def save_crawl_history(status):
    """Sauvegarde l'historique des crawls"""
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except:
            history = []

    history.append({
        'timestamp': datetime.now().isoformat(),
        'pages_indexed': status.get('pages_indexed', 0),
        'sites_crawled': status.get('sites_crawled', 0),
        'errors': status.get('errors', 0),
        'duration': status.get('last_crawl_duration_sec', 0)
    })

    history = history[-100:]

    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except:
        pass


def load_crawl_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []


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


def start_crawler(site=None, force=False, workers=None):
    if is_crawler_running():
        st.toast("Le crawler est déjà en cours d'exécution.", icon="⚠️")
        return

    try:
        python_executable = sys.executable
        cmd = [python_executable, CRAWLER_SCRIPT]

        if site:
            cmd.extend(["--site", site])
        if force:
            cmd.append("--force")
        if workers:
            cmd.extend(["--workers", str(workers)])

        process = subprocess.Popen(cmd)
        with open(PID_FILE, "w") as f:
            f.write(str(process.pid))

        msg = f"Crawler démarré"
        if site:
            msg += f" pour le site '{site}'"
        st.toast(msg + " !", icon="🚀")
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
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Erreur lors de la suppression du cache: {e}")
    else:
        st.toast("Aucun cache à vider.", icon="ℹ️")


# =======================
#  CSS Custom
# =======================
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .error-box {
        background-color: rgba(239, 68, 68, 0.1);
        border-left: 4px solid #ef4444;
        padding: 12px;
        margin: 8px 0;
        border-radius: 6px;
        color: inherit;
    }
    .error-box small {
        color: #ef4444;
        font-weight: 600;
    }
    .success-box {
        background-color: rgba(34, 197, 94, 0.1);
        border-left: 4px solid #22c55e;
        padding: 12px;
        margin: 8px 0;
        border-radius: 6px;
        color: inherit;
    }
    .warning-box {
        background-color: rgba(251, 191, 36, 0.1);
        border-left: 4px solid #fbbf24;
        padding: 12px;
        margin: 8px 0;
        border-radius: 6px;
        color: inherit;
    }
</style>
""", unsafe_allow_html=True)

# =======================
#  Affichage Principal
# =======================
st.title("🕸️ MeiliSearchCrawler Dashboard")
st.markdown("**Monitoring en temps réel** pour votre crawler KidSearch")

running = is_crawler_running()

# =======================
#  SIDEBAR: Navigation
# =======================
with st.sidebar:
    st.image("https://raw.githubusercontent.com/meilisearch/meilisearch/main/assets/logo.svg", width=100)
    st.title("Navigation")

    page = st.radio(
        "Choisir une section:",
        ["🏠 Vue d'ensemble", "🔧 Contrôles", "🔍 Recherche", "📊 Statistiques", "⚙️ Configuration", "🪵 Logs"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.metric("Statut", "🟢 Actif" if running else "🔴 Arrêté")

    if meili_client:
        try:
            index_ref = meili_client.index(INDEX_NAME)
            stats = index_ref.get_stats()
            num_docs = getattr(stats, 'number_of_documents', getattr(stats, 'numberOfDocuments', 0))
            st.metric("Documents indexés", f"{num_docs:,}")
        except:
            st.metric("Documents indexés", "N/A")

    cache_stats = load_cache_stats()
    if cache_stats:
        st.metric("URLs en cache", f"{cache_stats['total_urls']:,}")

# =======================
#  PAGE: Vue d'ensemble
# =======================
if page == "🏠 Vue d'ensemble":
    status = load_status()

    col1, col2, col3, col4 = st.columns(4)

    if status:
        with col1:
            st.metric(
                "Sites Crawlés",
                f"{status.get('sites_crawled', 0)} / {status.get('total_sites', 0)}",
                delta=None
            )
        with col2:
            st.metric("Pages Indexées", f"{status.get('pages_indexed', 0):,}")
        with col3:
            st.metric("Erreurs", status.get("errors", 0), delta_color="inverse")
        with col4:
            duration = status.get('last_crawl_duration_sec', 0)
            st.metric("Dernière Durée", f"{duration}s")

        if status.get('total_sites', 0) > 0:
            progress = status.get("sites_crawled", 0) / status["total_sites"]
            st.progress(progress, text=f"Progression: {progress * 100:.1f}%")

        active_site = status.get('active_site')
        if active_site and running:
            st.info(f"🔄 **Site en cours de crawl :** `{active_site}`")

        history = load_crawl_history()
        if len(history) > 1:
            st.subheader("📈 Évolution des Crawls")
            df_history = pd.DataFrame(history)
            df_history['timestamp'] = pd.to_datetime(df_history['timestamp'])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_history['timestamp'],
                y=df_history['pages_indexed'],
                mode='lines+markers',
                name='Pages Indexées',
                line=dict(color='#667eea', width=3)
            ))
            fig.update_layout(
                title="Évolution du nombre de pages indexées",
                xaxis_title="Date",
                yaxis_title="Pages",
                hovermode='x unified',
                height=300
            )
            st.plotly_chart(fig, use_container_width=True)

        if "stats" in status and status["stats"]:
            st.subheader("🌍 Performance par Site")
            df = pd.DataFrame(status["stats"])
            if not df.empty:
                fig = px.bar(
                    df, x="site", y="pages", color="status",
                    title="Pages indexées par site",
                    text="pages",
                    color_discrete_map={
                        'completed': '#10b981',
                        'in_progress': '#3b82f6',
                        'error': '#f59e0b',
                        'success': '#10b981'
                    }
                )
                fig.update_traces(textposition='outside')
                fig.update_layout(
                    xaxis_title="Site",
                    yaxis_title="Nombre de pages",
                    showlegend=True,
                    legend_title_text="Statut"
                )
                st.plotly_chart(fig, use_container_width=True)

                with st.expander("📋 Voir le tableau détaillé"):
                    st.dataframe(df, use_container_width=True)
    else:
        st.warning("⚠️ Aucun statut de crawl disponible. Lancez un crawl pour commencer !")
        if st.button("🚀 Lancer le premier crawl", type="primary"):
            start_crawler()

    st.markdown("---")
    if running:
        col1, col2 = st.columns([3, 1])
        with col1:
            refresh_rate = st.slider("⏱️ Actualisation automatique (secondes)", 5, 60, 10, key="refresh_slider")
        with col2:
            st.write("")
            st.write("")
            if st.button("⏸️ Pause auto-refresh"):
                st.session_state.pause_refresh = True

        if 'pause_refresh' not in st.session_state or not st.session_state.pause_refresh:
            status = load_status()
            if status:
                save_crawl_history(status)
            time.sleep(refresh_rate)
            st.rerun()
    else:
        st.caption("💡 Le dashboard s'actualise automatiquement pendant les crawls.")

# =======================
#  PAGE: Contrôles
# =======================
elif page == "🔧 Contrôles":
    st.header("⚙️ Contrôles du Crawler")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Options de Crawl")

        sites_config = load_sites_config()
        site_names = ["Tous les sites"]
        if sites_config and 'sites' in sites_config:
            site_names += [site['name'] for site in sites_config['sites']]

        selected_site = st.selectbox("Site à crawler:", site_names)
        force_crawl = st.checkbox("🔄 Force (ignorer le cache)", value=False)
        workers = st.slider("👥 Nombre de workers parallèles", 1, 20, 5)

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
            result = subprocess.run(
                [sys.executable, CRAWLER_SCRIPT, "--stats-only"],
                capture_output=True,
                text=True
            )
            st.code(result.stdout, language='text')

    st.subheader("⚠️ Erreurs Récentes")
    errors = parse_logs_for_errors(50)
    if errors:
        for err in errors[-10:]:
            st.markdown(f"""
            <div class="error-box">
                <small>{err['timestamp']}</small><br>
                <code style="font-size: 0.85em;">{err['message']}</code>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="success-box">
            ✅ Aucune erreur récente détectée
        </div>
        """, unsafe_allow_html=True)

    if running:
        st.markdown("---")
        st.caption("💡 Actualisation automatique toutes les 10 secondes pendant le crawl...")
        time.sleep(10)
        st.rerun()

# =======================
#  PAGE: Recherche
# =======================
elif page == "🔍 Recherche":
    st.header("🔬 Test de Recherche")

    if not meili_client:
        st.error("❌ Connexion à Meilisearch échouée. Vérifiez votre configuration.")
    else:
        try:
            index = meili_client.index(INDEX_NAME)


            @st.cache_data(ttl=300)
            def get_available_sites():
                try:
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
                query = st.text_input(
                    "🔍 Rechercher:",
                    placeholder="Ex: histoire de France, animaux, sciences...",
                    key="search_query"
                )
            with col2:
                selected_sites = st.multiselect("Filtrer par site:", options=available_sites)

            if query:
                search_params = {
                    'limit': 20,
                    'attributesToHighlight': ['title', 'excerpt'],
                    'highlightPreTag': '<mark>',
                    'highlightPostTag': '</mark>'
                }
                if selected_sites:
                    filters = ' OR '.join([f'site = "{site}"' for site in selected_sites])
                    search_params['filter'] = filters

                search_results = index.search(query, search_params)

                col1, col2 = st.columns(2)
                col1.metric("Résultats trouvés", search_results['estimatedTotalHits'])
                col2.metric("Temps de recherche", f"{search_results['processingTimeMs']}ms")

                if search_results['hits']:
                    st.markdown("---")
                    for i, hit in enumerate(search_results['hits'], 1):
                        formatted = hit.get('_formatted', {})

                        with st.container():
                            col1, col2 = st.columns([10, 1])
                            with col1:
                                st.markdown(f"""
                                <div style="border-left: 3px solid #667eea; padding-left: 15px; margin-bottom: 20px;">
                                    <h4 style="margin-bottom: 5px;">
                                        {i}. <a href="{hit['url']}" target="_blank">{formatted.get('title', hit['title'])}</a>
                                    </h4>
                                    <small style="color: #666;">
                                        <b>Site:</b> {hit['site']} | <b>URL:</b> {hit['url'][:60]}...
                                    </small>
                                    <p style="margin-top: 10px;">{formatted.get('excerpt', hit.get('excerpt', ''))[:300]}...</p>
                                </div>
                                """, unsafe_allow_html=True)
                else:
                    st.info("🔍 Aucun résultat trouvé pour cette recherche.")

        except Exception as e:
            st.error(f"❌ Une erreur est survenue lors de la recherche: {e}")

# =======================
#  PAGE: Statistiques
# =======================
elif page == "📊 Statistiques":
    st.header("📈 Statistiques Détaillées")

    if meili_client:
        try:
            index_ref = meili_client.index(INDEX_NAME)
            stats = index_ref.get_stats()

            try:
                index_info = meili_client.get_index(INDEX_NAME)
                updated_at = index_info.updated_at
            except:
                updated_at = None

            col1, col2, col3, col4 = st.columns(4)

            num_docs = getattr(stats, 'number_of_documents', getattr(stats, 'numberOfDocuments', 0))
            col1.metric("📄 Documents", f"{num_docs:,}")

            is_indexing = getattr(stats, 'is_indexing', getattr(stats, 'isIndexing', False))
            col2.metric("⚡ Indexation", "En cours" if is_indexing else "Idle")

            last_update = "Jamais"
            if updated_at:
                if isinstance(updated_at, str):
                    try:
                        dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        last_update = dt.strftime('%d/%m/%Y %H:%M')
                    except:
                        last_update = updated_at
                else:
                    last_update = updated_at.strftime('%d/%m/%Y %H:%M')
            col3.metric("🕐 Dernière MAJ", last_update)

            try:
                tasks_response = meili_client.get_tasks({
                    'indexUids': [INDEX_NAME],
                    'statuses': ['enqueued', 'processing'],
                    'limit': 1000
                })
                if hasattr(tasks_response, 'total'):
                    pending_tasks = tasks_response.total
                elif isinstance(tasks_response, dict):
                    pending_tasks = tasks_response.get('total', 0)
                else:
                    pending_tasks = 0
            except:
                pending_tasks = 0

            col4.metric("📋 Tâches actives", pending_tasks)

            st.markdown("---")
            st.subheader("💾 Volume de Données")

            field_distribution = {}

            try:
                if hasattr(stats, 'field_distribution'):
                    fd = stats.field_distribution
                    if isinstance(fd, dict):
                        field_distribution = fd
                    elif hasattr(fd, '__dict__'):
                        field_distribution = fd.__dict__
                    else:
                        try:
                            field_distribution = dict(fd)
                        except:
                            field_distribution = {}
                elif hasattr(stats, 'fieldDistribution'):
                    fd = stats.fieldDistribution
                    if isinstance(fd, dict):
                        field_distribution = fd
                    elif hasattr(fd, '__dict__'):
                        field_distribution = fd.__dict__
                    else:
                        try:
                            field_distribution = dict(fd)
                        except:
                            field_distribution = {}
            except Exception as e:
                st.warning(f"Impossible de récupérer la distribution des champs: {e}")
                field_distribution = {}

            col1, col2, col3, col4 = st.columns(4)

            if field_distribution:
                try:
                    total_fields = sum(field_distribution.values())
                except:
                    total_fields = 0

                avg_fields_per_doc = total_fields / num_docs if num_docs > 0 else 0
                estimated_size_mb = (num_docs * 1.5) / 1024

                col1.metric("💽 Taille estimée", f"{estimated_size_mb:.2f} MB")
                col2.metric("📊 Champs totaux", f"{total_fields:,}")
                col3.metric("📈 Champs/doc (moy)", f"{avg_fields_per_doc:.1f}")

                avg_doc_size_kb = (estimated_size_mb * 1024) / num_docs if num_docs > 0 else 0
                col4.metric("📦 Taille/doc (moy)", f"{avg_doc_size_kb:.2f} KB")
            else:
                estimated_size_mb = (num_docs * 1.5) / 1024
                col1.metric("💽 Taille estimée", f"{estimated_size_mb:.2f} MB")
                col2.metric("📊 Champs totaux", "N/A")
                col3.metric("📈 Champs/doc (moy)", "N/A")
                avg_doc_size_kb = (estimated_size_mb * 1024) / num_docs if num_docs > 0 else 0
                col4.metric("📦 Taille/doc (moy)", f"{avg_doc_size_kb:.2f} KB")

            if field_distribution:
                st.markdown("---")
                st.subheader("🔤 Distribution des Champs")

                try:
                    clean_field_dist = {}
                    for k, v in field_distribution.items():
                        if isinstance(v, (int, float)):
                            clean_field_dist[k] = int(v)
                        elif isinstance(v, dict):
                            if 'count' in v:
                                clean_field_dist[k] = int(v['count'])
                            else:
                                clean_field_dist[k] = len(v)

                    df_fields = pd.DataFrame([
                        {'Champ': k, 'Occurrences': v, 'Présence (%)': (v / num_docs) * 100 if num_docs > 0 else 0}
                        for k, v in sorted(clean_field_dist.items(), key=lambda x: x[1], reverse=True)
                    ])

                    col1, col2 = st.columns([2, 1])

                    with col1:
                        fig = px.bar(
                            df_fields.head(10),
                            y='Champ',
                            x='Occurrences',
                            orientation='h',
                            title='Top 10 des champs les plus utilisés',
                            text='Occurrences',
                            color='Présence (%)',
                            color_continuous_scale='Viridis'
                        )
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True)

                    with col2:
                        st.dataframe(
                            df_fields.style.format({
                                'Occurrences': '{:,.0f}',
                                'Présence (%)': '{:.1f}%'
                            }),
                            use_container_width=True,
                            hide_index=True,
                            height=400
                        )
                except Exception as e:
                    st.warning(f"Impossible d'afficher la distribution des champs: {e}")

            st.info(
                "💡 **Note :** La taille estimée est approximative. Pour une mesure précise, vérifiez l'espace disque utilisé par Meilisearch sur votre serveur.")

            st.markdown("---")
            st.subheader("🌐 Distribution des Documents par Site")
            try:
                result = index_ref.search("", {
                    'facets': ['site'],
                    'limit': 0
                })
                if 'facetDistribution' in result and 'site' in result['facetDistribution']:
                    facets = result['facetDistribution']['site']
                    df_facets = pd.DataFrame([
                        {'Site': k, 'Documents': v} for k, v in facets.items()
                    ]).sort_values('Documents', ascending=False)

                    col1, col2 = st.columns([2, 1])

                    with col1:
                        fig = px.pie(
                            df_facets,
                            values='Documents',
                            names='Site',
                            title='Répartition des documents par site',
                            hole=0.4
                        )
                        fig.update_traces(textposition='inside', textinfo='percent+label')
                        st.plotly_chart(fig, use_container_width=True)

                    with col2:
                        st.dataframe(
                            df_facets,
                            use_container_width=True,
                            hide_index=True
                        )

                    st.markdown("---")
                    st.subheader("🔍 Explorer les Documents par Site")

                    selected_site = st.selectbox(
                        "Choisir un site à explorer:",
                        options=df_facets['Site'].tolist(),
                        key="site_explorer"
                    )

                    if selected_site:
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            search_in_site = st.text_input(
                                f"Rechercher dans {selected_site}:",
                                placeholder="Laissez vide pour voir les derniers documents",
                                key="search_in_site"
                            )
                        with col2:
                            limit = st.selectbox("Résultats:", [10, 25, 50, 100], index=1)

                        search_params = {
                            'filter': f'site = "{selected_site}"',
                            'limit': limit,
                            'attributesToRetrieve': ['title', 'url', 'excerpt', 'site', 'lang']
                        }

                        if search_in_site:
                            site_results = index_ref.search(search_in_site, search_params)
                        else:
                            site_results = index_ref.search("", search_params)

                        st.info(
                            f"📊 **{site_results['estimatedTotalHits']}** documents trouvés pour **{selected_site}**")

                        if site_results['hits']:
                            docs_data = []
                            for hit in site_results['hits']:
                                docs_data.append({
                                    'Titre': hit.get('title', 'N/A')[:80] + (
                                        '...' if len(hit.get('title', '')) > 80 else ''),
                                    'URL': hit.get('url', 'N/A'),
                                    'Extrait': hit.get('excerpt', 'N/A')[:100] + (
                                        '...' if len(hit.get('excerpt', '')) > 100 else ''),
                                    'Langue': hit.get('lang', 'N/A')
                                })

                            df_docs = pd.DataFrame(docs_data)

                            for idx, hit in enumerate(site_results['hits']):
                                with st.expander(f"📄 {idx + 1}. {hit.get('title', 'Sans titre')[:80]}..."):
                                    col1, col2 = st.columns([3, 1])
                                    with col1:
                                        st.markdown(f"**URL:** [{hit.get('url', 'N/A')}]({hit.get('url', '#')})")
                                        st.markdown(
                                            f"**Extrait:** {hit.get('excerpt', 'Aucun extrait disponible')[:300]}...")
                                    with col2:
                                        if 'lang' in hit:
                                            st.metric("Langue", hit['lang'])
                                        if 'image' in hit and hit['image']:
                                            st.image(hit['image'], width=100)

                            csv = df_docs.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label="📥 Télécharger en CSV",
                                data=csv,
                                file_name=f"{selected_site.replace(' ', '_')}_documents.csv",
                                mime="text/csv",
                            )
                        else:
                            st.warning("Aucun document trouvé pour ce site.")
            except Exception as e:
                st.warning(f"Impossible de récupérer la distribution: {e}")

        except Exception as e:
            st.error(f"❌ Impossible de récupérer les stats: {e}")
    else:
        st.error("❌ Connexion à Meilisearch non disponible")

    if running:
        st.markdown("---")
        st.caption("💡 Actualisation automatique toutes les 15 secondes...")
        time.sleep(15)
        st.rerun()

# =======================
#  PAGE: Configuration
# =======================
elif page == "⚙️ Configuration":
    st.header("⚙️ Configuration des Sites")

    sites_config = load_sites_config()

    if sites_config is None:
        st.error("❌ Impossible de charger la configuration. Vérifiez que `config/sites.yml` existe.")
    else:
        tab1, tab2 = st.tabs(["📝 Éditeur", "👁️ Aperçu"])

        with tab1:
            st.info(
                "💡 Modifiez la configuration YAML ci-dessous. Attention : les modifications prendront effet au prochain crawl.")

            config_text = yaml.dump(sites_config, default_flow_style=False, allow_unicode=True)
            edited_config = st.text_area(
                "Configuration sites.yml:",
                value=config_text,
                height=400,
                key="config_editor"
            )

            col1, col2, col3 = st.columns([1, 1, 4])

            with col1:
                if st.button("💾 Sauvegarder", type="primary", disabled=running):
                    try:
                        new_config = yaml.safe_load(edited_config)
                        if save_sites_config(new_config):
                            st.success("✅ Configuration sauvegardée avec succès !")
                            time.sleep(1)
                            st.rerun()
                    except yaml.YAMLError as e:
                        st.error(f"❌ Erreur YAML: {e}")

            with col2:
                if st.button("🔄 Réinitialiser"):
                    st.rerun()

        with tab2:
            if 'sites' in sites_config:
                st.subheader(f"📋 {len(sites_config['sites'])} sites configurés")

                for site in sites_config['sites']:
                    with st.expander(f"🌐 {site['name']}", expanded=False):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Type:** {site['type']}")
                            st.write(f"**URL:** {site['crawl']}")
                            st.write(f"**Max pages:** {site.get('max_pages', 'N/A')}")
                        with col2:
                            st.write(f"**Profondeur:** {site.get('depth', 'N/A')}")
                            st.write(f"**Délai:** {site.get('delay', 'Auto')}s")
                            if 'lang' in site:
                                st.write(f"**Langue:** {site['lang']}")

                        if 'exclude' in site and site['exclude']:
                            st.write(f"**Exclusions:** {len(site['exclude'])} règles")
                            with st.expander("Voir les règles d'exclusion"):
                                for excl in site['exclude']:
                                    st.code(excl, language='text')

# =======================
#  PAGE: Logs
# =======================
elif page == "🪵 Logs":
    st.header("🪵 Logs du Crawler")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        num_lines = st.slider("Nombre de lignes à afficher:", 10, 500, 100)
    with col2:
        filter_level = st.selectbox("Filtrer par niveau:", ["Tous", "ERROR", "WARNING", "INFO", "DEBUG"])
    with col3:
        if st.button("🔄 Actualiser"):
            st.rerun()

    if not os.path.exists(LOG_FILE):
        st.warning("📝 Aucun fichier de log trouvé. Les logs apparaîtront après le premier crawl.")
    else:
        try:
            with open(LOG_FILE, "r", encoding='utf-8') as f:
                lines = f.readlines()[-num_lines:]

            if filter_level != "Tous":
                lines = [l for l in lines if filter_level in l]

            log_content = "".join(lines)

            log_content = log_content.replace("ERROR", "🔴 ERROR")
            log_content = log_content.replace("WARNING", "🟡 WARNING")
            log_content = log_content.replace("INFO", "🔵 INFO")

            st.code(log_content, language='log')

            st.subheader("📊 Statistiques des Logs")
            col1, col2, col3 = st.columns(3)

            with open(LOG_FILE, "r", encoding='utf-8') as f:
                all_lines = f.readlines()

            col1.metric("Total de lignes", len(all_lines))
            col2.metric("Erreurs", sum(1 for l in all_lines if 'ERROR' in l))
            col3.metric("Warnings", sum(1 for l in all_lines if 'WARNING' in l))

        except Exception as e:
            st.error(f"❌ Erreur lors de la lecture des logs: {e}")

    if running:
        st.markdown("---")
        st.caption("💡 Actualisation automatique toutes les 5 secondes...")
        time.sleep(5)
        st.rerun()