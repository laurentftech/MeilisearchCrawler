import uvicorn
import sys
from pathlib import Path

if __name__ == "__main__":
    # Ajoute le répertoire du projet au PYTHONPATH
    # C'est la clé pour que les imports fonctionnent
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))

    uvicorn.run(
        "meilisearchcrawler.api.server:app",  # CORRECTION: Utilisation de server.py
        host="127.0.0.1",
        port=8000,
        reload=True
    )
