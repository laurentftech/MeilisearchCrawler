import streamlit as st
import os
from streamlit_oauth import OAuth2Component
from dashboard.src.i18n import get_translator

def check_authentication():
    """
    Vérifie si l'utilisateur est authentifié via OAuth2.
    Affiche le bouton de connexion si nécessaire et arrête l'exécution de la page.
    Retourne les informations du token si l'utilisateur est authentifié.
    """
    # Utiliser le traducteur pour le bouton de connexion
    lang = st.session_state.get('lang', 'fr')
    t = get_translator(lang)

    # Configuration du client OAuth2 (doit être définie dans les variables d'env)
    AUTHORIZE_URL = os.getenv("OAUTH_AUTHORIZE_URL")
    TOKEN_URL = os.getenv("OAUTH_TOKEN_URL")
    CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
    CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")
    REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")
    SCOPE = "openid profile email"

    # Vérifier que la configuration est présente
    if not all([AUTHORIZE_URL, TOKEN_URL, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
        st.error(t('oauth_config_error'))
        st.stop()

    # Créer le composant d'authentification
    oauth2 = OAuth2Component(CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, TOKEN_URL, REDIRECT_URI)

    # Si le token n'est pas dans la session, afficher le bouton de connexion
    if 'token' not in st.session_state:
        st.title(f"🔒 {t('auth_required')}")
        st.markdown(t('please_log_in'))
        
        result = oauth2.authorize_button(
            name=t('login_with_sso'),
            icon="https://raw.githubusercontent.com/meilisearch/meilisearch/main/assets/logo.svg",
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            key="oauth_login",
            use_container_width=True
        )
        
        if result:
            st.session_state.token = result.get('token')
            st.rerun()
        
        # Arrêter l'exécution de la page pour ne rien afficher d'autre
        st.stop()

    # Si on arrive ici, le token est dans la session, l'utilisateur est authentifié
    return st.session_state.get('token')
