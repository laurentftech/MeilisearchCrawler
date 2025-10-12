import streamlit as st
import subprocess
import sys
import time
import os

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
@st.cache_data(ttl=30, show_spinner=t("embeddings.loading_stats_spinner"))
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
            return {"total": 0, "with_vectors": 0, "without_vectors": 0}
        
        res = index.search("", {'filter': '_vectors IS NULL OR _vectors NOT EXISTS', 'limit': 0})
        without_vectors = res.get('estimatedTotalHits', 0)
        
        return {
            "total": total_docs,
            "with_vectors": total_docs - without_vectors,
            "without_vectors": without_vectors
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
    process = subprocess.Popen(
        [python_executable, EMBEDDING_SCRIPT_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        bufsize=1
    )
    st.session_state.embedding_process = process
    st.session_state.embedding_output = []


# --- Affichage de la page ---
st.markdown("***")
st.subheader(t("embeddings.stats_title"))

col_btn_1, col_btn_2 = st.columns([4, 1])
with col_btn_2:
    if st.button(f"🔄 {t('embeddings.refresh_button')}"):
        # Vider le cache pour forcer le rechargement des stats
        st.cache_data.clear()

stats = get_embedding_stats(force_refresh_key=time.time())

if stats:
    total = stats['total']
    with_vectors = stats['with_vectors']
    without_vectors = stats['without_vectors']

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t("embeddings.total_docs"), f"{total:,}")
    col2.metric(t("embeddings.docs_with_vectors"), f"{with_vectors:,}")
    col3.metric(t("embeddings.docs_without_vectors"), f"{without_vectors:,}")

    if total > 0:
        completion_rate = with_vectors / total
        col4.metric(t("embeddings.completion_rate"), f"{completion_rate:.1%}")
        st.progress(completion_rate)
    else:
        col4.metric(t("embeddings.completion_rate"), "N/A")
        st.progress(0.0)

    st.markdown("***")
    st.subheader(t("embeddings.actions_title"))

    # Bouton pour lancer le processus
    if without_vectors == 0 and total > 0:
        st.success(t("embeddings.all_docs_processed"), icon="🎉")
    else:
        st.button(
            t("embeddings.generate_button"),
            on_click=run_embedding_process,
            disabled=("embedding_process" in st.session_state and st.session_state.embedding_process.poll() is None)
        )
else:
    st.warning("Impossible de charger les statistiques. Le client Meilisearch est-il disponible ?")

# --- Suivi du processus en cours ---
if "embedding_process" in st.session_state:
    process = st.session_state.embedding_process

    with st.expander(t("embeddings.process_output"), expanded=True):
        output_container = st.empty()
        
        # Lire la sortie en continu
        while process.poll() is None:
            line = process.stdout.readline()
            if line:
                st.session_state.embedding_output.append(line.strip())
                output_container.code("\n".join(st.session_state.embedding_output), language="log")
            time.sleep(0.1) # Petite pause pour ne pas surcharger

        # Assurer que toute la sortie restante est lue
        for line in process.stdout.readlines():
            st.session_state.embedding_output.append(line.strip())
        
        output_container.code("\n".join(st.session_state.embedding_output), language="log")
        st.toast(t("embeddings.process_finished"), icon="✅")
        # Nettoyer la session une fois le processus terminé
        del st.session_state.embedding_process
        del st.session_state.embedding_output
        st.rerun()
