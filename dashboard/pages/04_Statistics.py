import streamlit as st
import subprocess
import sys
import time
import os
import re

from src.i18n import get_translator
from src.meilisearch_client import get_meili_client
from src.config import INDEX_NAME, BASE_DIR

# Initialiser le traducteur
if 'lang' not in st.session_state:
    st.session_state.lang = "fr"
t = get_translator(st.session_state.lang)

st.title(t("embeddings.title"))
st.markdown(t("embeddings.subtitle"))
st.info(t("embeddings.info_what_are_embeddings"), icon="🧠")

# Chemin vers le script à exécuter
EMBEDDING_SCRIPT_PATH = os.path.join(BASE_DIR, "meilisearchcrawler", "meilisearch_gemini.py")


# --- Fonctions de la page ---
@st.cache_data(ttl=10, show_spinner=t("embeddings.loading_stats_spinner"))
def get_embedding_stats(force_refresh_key=None):
    """Récupère les statistiques sur les embeddings depuis Meilisearch."""
    client = get_meili_client()
    if not client:
        return None
    try:
        index = client.index(INDEX_NAME)
        stats = index.get_stats()
        total_docs = getattr(stats, 'number_of_documents', 0)

        if total_docs == 0:
            return {"total": 0, "with_vectors": 0, "without_vectors": 0, "config_ok": False}

        # Vérifier la configuration des embedders
        settings = index.get_settings()
        embedders = settings.get('embedders', {})
        has_default = 'default' in embedders
        has_query = 'query' in embedders
        config_ok = has_default and has_query

        # Compter les documents sans embeddings (filtre corrigé)
        res = index.search("", {'filter': '_vectors.default NOT EXISTS', 'limit': 0})
        without_vectors = res.get('estimatedTotalHits', 0)

        return {
            "total": total_docs,
            "with_vectors": total_docs - without_vectors,
            "without_vectors": without_vectors,
            "config_ok": config_ok,
            "has_default": has_default,
            "has_query": has_query
        }
    except Exception as e:
        st.error(f"{t('embeddings.error_stats')}: {e}")
        return None


def run_embedding_process():
    """Lance le script de génération d'embeddings en arrière-plan."""
    if "embedding_process" in st.session_state and st.session_state.embedding_process.poll() is None:
        st.toast(t("embeddings.process_running"), icon="⚠️")
        return

    st.toast(t("embeddings.process_starting"), icon="🚀")
    python_executable = sys.executable

    # Utiliser Popen avec un buffer line par line
    process = subprocess.Popen(
        [python_executable, "-u", EMBEDDING_SCRIPT_PATH],  # -u pour unbuffered
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        bufsize=1,
        universal_newlines=True
    )
    st.session_state.embedding_process = process
    st.session_state.embedding_output = []
    st.session_state.last_update_time = time.time()


def parse_progress_from_output(output_lines):
    """Extrait les informations de progression depuis la sortie."""
    processed = 0
    total = 0
    successful = 0

    for line in reversed(output_lines):  # Commencer par les lignes les plus récentes
        # Chercher "Documents traités: X"
        if "Documents traités:" in line:
            match = re.search(r'Documents traités:\s*(\d+)', line)
            if match:
                processed = int(match.group(1))

        # Chercher "Trouvé: X documents"
        if "Trouvé:" in line and "documents sans embeddings" in line:
            match = re.search(r'Trouvé:\s*(\d+)', line)
            if match:
                total = int(match.group(1))

        # Chercher "Embeddings ajoutés: X"
        if "Embeddings ajoutés:" in line:
            match = re.search(r'Embeddings ajoutés:\s*(\d+)', line)
            if match:
                successful = int(match.group(1))

        if total > 0 and processed > 0:
            break

    return processed, total, successful


# --- Affichage de la page ---
st.markdown("***")
st.subheader(t("embeddings.stats_title"))

col_btn_1, col_btn_2 = st.columns([4, 1])
with col_btn_2:
    if st.button(f"🔄 {t('embeddings.refresh_button')}"):
        st.cache_data.clear()
        st.rerun()

# Auto-refresh si un processus est en cours
if "embedding_process" in st.session_state:
    if st.session_state.embedding_process.poll() is None:
        # Processus en cours, rafraîchir automatiquement
        time.sleep(0.5)
        st.rerun()

stats = get_embedding_stats(force_refresh_key=time.time())

if stats:
    total = stats['total']
    with_vectors = stats['with_vectors']
    without_vectors = stats['without_vectors']
    config_ok = stats['config_ok']

    # Alerte si configuration incomplète
    if not config_ok:
        st.error("⚠️ Configuration incomplète des embedders!", icon="🚨")
        if not stats['has_default']:
            st.warning("Embedder 'default' manquant")
        if not stats['has_query']:
            st.warning("Embedder 'query' manquant")
        st.info("Exécutez: `python configure_and_check_meilisearch.py` pour configurer les embedders")
        st.stop()

    # Métriques
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t("embeddings.total_docs"), f"{total:,}")
    col2.metric(t("embeddings.docs_with_vectors"), f"{with_vectors:,}",
                delta=None if without_vectors == 0 else f"{with_vectors}")
    col3.metric(t("embeddings.docs_without_vectors"), f"{without_vectors:,}",
                delta=None if without_vectors == 0 else f"-{without_vectors}", delta_color="inverse")

    if total > 0:
        completion_rate = with_vectors / total
        col4.metric(t("embeddings.completion_rate"), f"{completion_rate:.1%}")
        st.progress(completion_rate, text=f"{with_vectors:,} / {total:,} documents")
    else:
        col4.metric(t("embeddings.completion_rate"), "N/A")
        st.progress(0.0)

    st.markdown("***")
    st.subheader(t("embeddings.actions_title"))

    # Estimation du temps et coût
    if without_vectors > 0:
        estimated_batches = (without_vectors // 50) + 1
        estimated_time_min = estimated_batches * 10 / 60  # ~10s par batch

        st.info(f"""
        📊 **Estimation pour {without_vectors:,} documents manquants:**
        - Nombre de requêtes API: ~{estimated_batches:,}
        - Temps estimé: ~{estimated_time_min:.0f} minutes
        - Batch size: 50 documents par requête
        """)

    # Bouton pour lancer le processus
    process_running = "embedding_process" in st.session_state and st.session_state.embedding_process.poll() is None

    if without_vectors == 0 and total > 0:
        st.success(t("embeddings.all_docs_processed"), icon="🎉")
    else:
        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn1:
            st.button(
                t("embeddings.generate_button") + f" ({without_vectors:,} documents)",
                on_click=run_embedding_process,
                disabled=process_running,
                type="primary",
                use_container_width=True
            )
        with col_btn2:
            if process_running:
                st.markdown("**🔄 En cours...**")
else:
    st.warning("⚠️ Impossible de charger les statistiques. Le client Meilisearch est-il disponible ?")

# --- Suivi du processus en cours ---
if "embedding_process" in st.session_state:
    process = st.session_state.embedding_process

    st.markdown("***")
    st.subheader("📊 Processus en cours")

    # Conteneur pour les métriques de progression
    progress_cols = st.columns(3)

    with st.expander(t("embeddings.process_output"), expanded=True):
        output_container = st.empty()

        # Lire la sortie en continu
        if process.poll() is None:
            # Processus en cours
            while True:
                line = process.stdout.readline()
                if not line:
                    break

                clean_line = line.strip()
                if clean_line:
                    st.session_state.embedding_output.append(clean_line)

                    # Limiter à 100 dernières lignes pour la performance
                    if len(st.session_state.embedding_output) > 100:
                        st.session_state.embedding_output = st.session_state.embedding_output[-100:]

                # Mettre à jour l'affichage toutes les 0.5s
                if time.time() - st.session_state.last_update_time > 0.5:
                    output_container.code("\n".join(st.session_state.embedding_output), language="log")
                    st.session_state.last_update_time = time.time()

                    # Extraire et afficher les métriques
                    processed, total_to_process, successful = parse_progress_from_output(
                        st.session_state.embedding_output)
                    if total_to_process > 0:
                        progress_cols[0].metric("Traités", f"{processed:,}")
                        progress_cols[1].metric("Réussis", f"{successful:,}")
                        progress_rate = processed / total_to_process if total_to_process > 0 else 0
                        progress_cols[2].metric("Progression", f"{progress_rate:.1%}")

                    time.sleep(0.5)
        else:
            # Processus terminé - lire la sortie restante
            remaining_output = process.stdout.read()
            if remaining_output:
                for line in remaining_output.split('\n'):
                    if line.strip():
                        st.session_state.embedding_output.append(line.strip())

            output_container.code("\n".join(st.session_state.embedding_output), language="log")

            # Afficher les métriques finales
            processed, total_to_process, successful = parse_progress_from_output(st.session_state.embedding_output)
            if total_to_process > 0:
                progress_cols[0].metric("✅ Traités", f"{processed:,}")
                progress_cols[1].metric("✅ Réussis", f"{successful:,}")
                progress_rate = processed / total_to_process if total_to_process > 0 else 0
                progress_cols[2].metric("✅ Progression", f"{progress_rate:.1%}")

            # Vérifier le code de retour
            if process.returncode == 0:
                st.success("✅ " + t("embeddings.process_finished"), icon="🎉")
            else:
                st.error(f"❌ Le processus s'est terminé avec une erreur (code: {process.returncode})")

            # Nettoyer la session
            del st.session_state.embedding_process
            del st.session_state.embedding_output
            st.cache_data.clear()

            # Attendre un peu avant de recharger pour que l'utilisateur voie le message
            time.sleep(2)
            st.rerun()