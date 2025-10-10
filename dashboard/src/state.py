import os
import signal
import subprocess
import sys
import time
import streamlit as st

from .config import PID_FILE, CRAWLER_SCRIPT, CACHE_FILE


def is_crawler_running():
    """Checks if the crawler process is currently running."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if the process exists
        return True
    except (IOError, ValueError, OSError):
        # PID file is stale or unreadable
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return False

def start_crawler(site=None, force=False, workers=None):
    """Starts the crawler as a background process."""
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

        # Using Popen to run in the background
        process = subprocess.Popen(cmd)
        with open(PID_FILE, "w") as f:
            f.write(str(process.pid))

        msg = f"Crawler démarré"
        if site:
            msg += f" pour le site '{site}'"
        st.toast(msg + " !", icon="🚀")
        time.sleep(2)  # Give time for the UI to update
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors du lancement du crawler: {e}")

def stop_crawler():
    """Stops the running crawler process."""
    if not os.path.exists(PID_FILE):
        st.toast("Le crawler n'est pas en cours d'exécution.", icon="ℹ️")
        return

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)  # Send termination signal
        st.toast("Signal d'arrêt envoyé au crawler.", icon="🛑")
        time.sleep(2)
    except (IOError, ValueError, OSError) as e:
        st.error(f"Erreur lors de l'arrêt du crawler: {e}")
    finally:
        # Ensure PID file is removed
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        st.rerun()

def clear_cache():
    """Deletes the crawler's cache file."""
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
