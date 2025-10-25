import os
import signal
import subprocess
import sys
import streamlit as st

from .config import PID_FILE, CRAWLER_SCRIPT

def is_crawler_running():
    """Checks if the crawler process is currently running."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (IOError, ValueError, OSError):
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return False

def start_crawler(site=None, force=False, workers=None, embed=False):
    """Starts the crawler as a background process. Returns True on success, False on failure."""
    if is_crawler_running():
        return False # Indique que le crawler tourne déjà

    try:
        python_executable = sys.executable
        cmd = [python_executable, CRAWLER_SCRIPT]
        if site: cmd.extend(["--site", site])
        if force: cmd.append("--force")
        if workers: cmd.extend(["--workers", str(workers)])
        if embed: cmd.append("--embeddings") # Ajout du flag pour les embeddings

        process = subprocess.Popen(cmd)
        with open(PID_FILE, "w") as f:
            f.write(str(process.pid))
        return True # Succès
    except Exception as e:
        st.error(f"Erreur lors du lancement du crawler: {e}")
        return False

def stop_crawler():
    """Stops the running crawler process. Returns True on success, False on failure."""
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        return True
    except (IOError, ValueError, OSError) as e:
        st.error(f"Erreur lors de l'arrêt du crawler: {e}")
        return False
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

def clear_cache():
    """Clears the crawler's cache by running the crawler script with --clear-cache."""
    try:
        python_executable = sys.executable
        cmd = [python_executable, CRAWLER_SCRIPT, "--clear-cache"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return True
        else:
            st.error(f"Erreur lors du nettoyage du cache: {result.stderr or result.stdout}")
            return False
    except Exception as e:
        st.error(f"Erreur lors de l\'exécution de la commande de nettoyage du cache: {e}")
        return False
