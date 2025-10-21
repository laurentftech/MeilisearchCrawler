import yaml
import os
import streamlit as st

# Chemin vers le dossier des traductions
LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'locales')

@st.cache_data
def load_translation(language: str) -> dict:
    """Charge le fichier de traduction YAML pour une langue donnée."""
    try:
        path = os.path.join(LOCALES_DIR, f'{language}.yml')
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # Si le fichier de la langue n'existe pas, on retourne un dictionnaire vide
        # On pourrait aussi charger une langue par défaut (ex: 'en')
        st.warning(f"Fichier de traduction pour '{language}' introuvable.")
        return {}

def get_translator(language: str):
    """Retourne une fonction de traduction qui récupère une clé dans le fichier de langue."""
    translations = load_translation(language)

    def t(key: str, **kwargs):
        # Navigue dans le dictionnaire si la clé est imbriquée (ex: "page.title")
        keys = key.split('.')
        value = translations
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                # Si la clé n'est pas trouvée, on la retourne telle quelle
                # pour faciliter le développement (on voit ce qui manque)
                return key
        
        if kwargs and isinstance(value, str):
            return value.format(**kwargs)
        
        return value    

    return t
