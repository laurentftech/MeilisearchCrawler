"""
Module d'authentification pour le Dashboard Streamlit.
Supporte Authentik (OpenID Connect), Google OAuth, GitHub OAuth et authentification simple.
"""

import streamlit as st
import os
import hashlib
import requests
import logging
from datetime import datetime
from urllib.parse import urlencode, parse_qs, urlparse
from typing import Optional, Dict, Any
from dashboard.src.i18n import get_translator
from dashboard.src.session_manager import get_session_manager
from meilisearchcrawler.auth_config import get_auth_config, AuthProvider

# Configuration du logging pour l'authentification
os.makedirs("data/logs", exist_ok=True)
auth_logger = logging.getLogger("auth")
auth_logger.setLevel(logging.INFO)  # Niveau INFO pour les événements importants

# Handler pour fichier
if not auth_logger.handlers:
    file_handler = logging.FileHandler("data/logs/auth.log")
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    auth_logger.addHandler(file_handler)


def _hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def _check_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return _hash_password(password) == hashed


def _simple_auth(t):
    """
    Authentification simple par mot de passe.
    Utilise DASHBOARD_PASSWORD depuis .env
    """
    auth_config = get_auth_config()
    dashboard_password = auth_config.get_simple_password()

    if not dashboard_password:
        st.error(t('simple_auth_not_configured'))
        st.info(t('simple_auth_help'))
        st.stop()

    st.title(f"🔒 {t('auth_required')}")
    st.markdown(t('please_log_in'))

    with st.form("login_form"):
        password = st.text_input(t('password_label'), type="password", key="password_input")
        submit = st.form_submit_button(t('login_button'), use_container_width=True)

        if submit:
            if password == dashboard_password:
                auth_logger.info("Simple password login SUCCESS")

                # Créer une session persistante
                session_manager = get_session_manager()
                user_info = {"name": "Dashboard User", "email": ""}
                session_id = session_manager.create_session(
                    email="",
                    user_info=user_info,
                    auth_method="password"
                )

                # Sauvegarder dans la session Streamlit
                st.session_state.authenticated = True
                st.session_state.auth_method = "password"
                st.session_state.user_info = user_info
                st.session_state.persistent_session_id = session_id

                st.rerun()
            else:
                auth_logger.warning("Simple password login FAILED - incorrect password")
                st.error(t('incorrect_password'))

    st.stop()


def _authentik_auth(t):
    """
    Authentification via Authentik (OpenID Connect).

    Args:
        t: Traducteur pour les messages
    """
    auth_config = get_auth_config()
    config = auth_config.get_authentik_config()

    if not config:
        st.error("Authentik authentication is not configured.")
        st.info("Please set AUTHENTIK_DOMAIN, AUTHENTIK_CLIENT_ID, and AUTHENTIK_CLIENT_SECRET in your .env file.")
        st.stop()

    # Gérer le callback OAuth
    query_params = st.query_params

    if "code" in query_params:
        # Étape 2: Échanger le code contre un token
        code = query_params["code"]

        try:
            # Préparer la redirection URI
            redirect_uri = os.getenv("AUTHENTIK_REDIRECT_URI", st.session_state.get("redirect_uri", "http://localhost:8501/"))

            # Échanger le code contre un token
            token_response = requests.post(
                config["token_url"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if token_response.status_code == 200:
                token_data = token_response.json()
                access_token = token_data.get("access_token")
                id_token = token_data.get("id_token")

                # Récupérer les informations utilisateur
                userinfo_response = requests.get(
                    config["userinfo_url"],
                    headers={"Authorization": f"Bearer {access_token}"}
                )

                if userinfo_response.status_code == 200:
                    user_info = userinfo_response.json()
                    user_email = user_info.get("email", "")

                    auth_logger.info(f"Authentik login attempt - email: {user_email}")

                    # Vérifier si l'email est autorisé
                    if not auth_config.is_email_allowed(user_email):
                        auth_logger.warning(f"Authentik access DENIED - email: {user_email} - not in ALLOWED_EMAILS")
                        st.error(f"🚫 {t('access_denied')}")
                        st.warning(f"{t('email_not_authorized')}: {user_email}")
                        st.info(t('contact_admin'))
                        st.stop()

                    # Préparer les informations utilisateur
                    user_data = {
                        "name": user_info.get("name", user_info.get("preferred_username", "User")),
                        "email": user_email,
                        "sub": user_info.get("sub", ""),
                    }

                    # Créer une session persistante
                    session_manager = get_session_manager()
                    session_id = session_manager.create_session(
                        email=user_email,
                        user_info=user_data,
                        auth_method="authentik",
                        token={"access_token": access_token, "id_token": id_token}
                    )

                    # Sauvegarder dans la session
                    st.session_state.authenticated = True
                    st.session_state.auth_method = "authentik"
                    st.session_state.oauth_token = access_token
                    st.session_state.id_token = id_token
                    st.session_state.user_info = user_data
                    st.session_state.persistent_session_id = session_id

                    auth_logger.info(f"Authentik login SUCCESS - email: {user_email}")

                    # Nettoyer les query params et rediriger
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(f"Failed to fetch user info: {userinfo_response.status_code}")
                    st.stop()
            else:
                st.error(f"Failed to exchange code for token: {token_response.status_code}")
                st.json(token_response.json())
                st.stop()

        except Exception as e:
            st.error(f"Authentication error: {str(e)}")
            st.stop()

    # Étape 1: Afficher le bouton de connexion
    st.title(f"🔒 {t('auth_required')}")
    st.markdown(t('please_log_in'))

    redirect_uri = os.getenv("AUTHENTIK_REDIRECT_URI", "http://localhost:8501/")
    st.session_state.redirect_uri = redirect_uri

    # Construire l'URL d'autorisation
    auth_params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(config["scopes"]),
    }

    auth_url = f"{config['authorize_url']}?{urlencode(auth_params)}"

    # Afficher le bouton de connexion
    st.markdown(
        f"""
        <a href="{auth_url}" target="_self">
            <button style="
                background-color: #ee0a84;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 4px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
            ">
                🔐 Login with Authentik
            </button>
        </a>
        """,
        unsafe_allow_html=True
    )

    st.stop()


def _oauth_auth(provider: str, t):
    """
    Authentification OAuth2 (Google ou Github) - version existante conservée.

    Args:
        provider: "google" ou "github"
        t: Traducteur pour les messages
    """
    try:
        from streamlit_oauth import OAuth2Component
    except ImportError:
        st.error("streamlit-oauth is not installed. Run: pip install streamlit-oauth")
        st.stop()

    auth_config = get_auth_config()

    # Configuration selon le provider
    if provider == "google":
        config = auth_config.get_google_config()
        button_text = t('login_with_google')
        icon = "https://www.google.com/favicon.ico"
        scope = "openid profile email"
    else:  # github
        config = auth_config.get_github_config()
        button_text = t('login_with_github')
        icon = "https://github.com/favicon.ico"
        scope = "read:user user:email"

    # Vérifier que la configuration est présente
    if not config:
        st.error(t('oauth_not_configured').format(provider=provider.title()))
        st.info(t('oauth_config_help').format(provider=provider.upper()))
        return False

    # Vérifier si on a déjà un token valide en session (persistance après rerun)
    session_key = f"{provider}_oauth_result"
    if session_key in st.session_state and st.session_state.get('authenticated'):
        # Déjà authentifié, pas besoin de redemander
        return True

    # Créer le composant d'authentification
    oauth2 = OAuth2Component(
        config["client_id"],
        config["client_secret"],
        config["authorize_url"],
        config["token_url"],
        config["token_url"],
        config["redirect_uri"]
    )

    # Bouton de connexion
    result = oauth2.authorize_button(
        name=button_text,
        icon=icon,
        redirect_uri=config["redirect_uri"],
        scope=scope,
        key=f"oauth_{provider}",
        use_container_width=True
    )

    if result:
        user_info = result.get('user', {})

        # Essayer plusieurs façons de récupérer l'email
        user_email = (
            user_info.get('email') or
            result.get('email') or
            result.get('userinfo', {}).get('email') or
            ''
        )

        # Si l'email est vide, essayer de le récupérer via l'API du provider
        if not user_email and result.get('token'):
            try:
                if provider == "google":
                    # Récupérer les infos via l'API Google
                    response = requests.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {result['token']['access_token']}"}
                    )
                    if response.status_code == 200:
                        google_info = response.json()
                        user_email = google_info.get('email', '')
                        # Mettre à jour user_info avec toutes les données
                        user_info.update(google_info)
                elif provider == "github":
                    # Récupérer les infos via l'API GitHub
                    response = requests.get(
                        "https://api.github.com/user",
                        headers={"Authorization": f"token {result['token']['access_token']}"}
                    )
                    if response.status_code == 200:
                        github_info = response.json()
                        user_email = github_info.get('email', '')
                        # Si l'email principal est privé, essayer de récupérer les emails publics
                        if not user_email:
                            emails_response = requests.get(
                                "https://api.github.com/user/emails",
                                headers={"Authorization": f"token {result['token']['access_token']}"}
                            )
                            if emails_response.status_code == 200:
                                emails = emails_response.json()
                                # Trouver l'email principal ou le premier vérifié
                                for email_obj in emails:
                                    if email_obj.get('primary') and email_obj.get('verified'):
                                        user_email = email_obj.get('email', '')
                                        break
                        user_info.update(github_info)
            except Exception as e:
                auth_logger.error(f"Erreur lors de la récupération de l'email via API {provider}: {str(e)}")

        auth_logger.info(f"{provider.upper()} OAuth login attempt - email: {user_email}")

        # Vérifier si l'email est autorisé
        if not auth_config.is_email_allowed(user_email):
            auth_logger.warning(f"{provider.upper()} OAuth access DENIED - email: {user_email} - not in ALLOWED_EMAILS")
            st.error(f"🚫 {t('access_denied')}")
            st.warning(f"{t('email_not_authorized')}: {user_email}")
            st.info(t('contact_admin'))
            st.stop()

        auth_logger.info(f"{provider.upper()} OAuth login SUCCESS - email: {user_email}")

        # Créer une session persistante
        session_manager = get_session_manager()
        session_id = session_manager.create_session(
            email=user_email,
            user_info=user_info,
            auth_method=provider,
            token=result.get('token')
        )

        # Sauvegarder les informations d'authentification dans la session
        st.session_state.authenticated = True
        st.session_state.auth_method = provider
        st.session_state.oauth_token = result.get('token')
        st.session_state.user_info = user_info
        st.session_state.persistent_session_id = session_id

        # Sauvegarder le résultat OAuth complet pour persistance
        st.session_state[f"{provider}_oauth_result"] = result

        st.rerun()

    return False


def check_authentication():
    """
    Vérifie si l'utilisateur est authentifié.
    Supporte 4 méthodes d'authentification :
    1. Authentik (OpenID Connect)
    2. Google OAuth
    3. Github OAuth
    4. Authentification simple par mot de passe

    Affiche l'interface de connexion si nécessaire et arrête l'exécution de la page.
    Retourne les informations utilisateur si authentifié.
    """
    # Utiliser le traducteur
    lang = st.session_state.get('lang', 'fr')
    t = get_translator(lang)

    # Récupérer le gestionnaire de sessions
    session_manager = get_session_manager()

    # Vérifier si on a un session_id valide dans le cache persistant
    if 'persistent_session_id' in st.session_state:
        session_id = st.session_state['persistent_session_id']
        session_data = session_manager.get_session(session_id)

        if session_data:
            # Restaurer l'authentification depuis la session persistante
            st.session_state.authenticated = True
            st.session_state.auth_method = session_data['auth_method']
            st.session_state.user_info = session_data['user_info']
            st.session_state.oauth_token = session_data.get('token')
            return session_data['user_info']

    # Vérifier si déjà authentifié dans la session Streamlit courante
    if st.session_state.get('authenticated', False):
        return st.session_state.get('user_info', {})

    # Charger la configuration d'authentification
    auth_config = get_auth_config()

    # Si l'authentification est désactivée, laisser passer
    if not auth_config.is_enabled:
        st.session_state.authenticated = True
        st.session_state.auth_method = "none"
        st.session_state.user_info = {"name": "Anonymous", "email": ""}
        return st.session_state.user_info

    # Déterminer les méthodes d'authentification disponibles
    providers = auth_config.providers

    # Si aucune méthode configurée, afficher une erreur
    if not providers or AuthProvider.NONE in providers:
        st.error(t('no_auth_configured'))
        st.info(t('auth_config_help'))
        st.stop()

    # Si une seule méthode disponible, l'utiliser directement
    if len(providers) == 1:
        provider = providers[0]
        if provider == AuthProvider.SIMPLE:
            _simple_auth(t)
        elif provider == AuthProvider.AUTHENTIK:
            _authentik_auth(t)
        elif provider == AuthProvider.GOOGLE:
            _oauth_auth("google", t)
        elif provider == AuthProvider.GITHUB:
            _oauth_auth("github", t)
        st.stop()

    # Afficher la page de connexion
    st.title(f"🔒 {t('auth_required')}")
    st.markdown(t('please_log_in'))

    # Sinon, afficher un sélecteur de méthode
    st.markdown("---")
    st.subheader(t('choose_auth_method'))

    # Créer des colonnes pour les boutons
    cols = st.columns(len(providers))

    for idx, provider in enumerate(providers):
        with cols[idx]:
            if provider == AuthProvider.AUTHENTIK:
                if st.button(
                    "🔐 Authentik",
                    key="btn_authentik",
                    use_container_width=True,
                    help="Login with Authentik"
                ):
                    st.session_state.selected_auth_method = "authentik"
                    st.rerun()

            elif provider == AuthProvider.GOOGLE:
                if st.button(
                    "🔵 Google",
                    key="btn_google",
                    use_container_width=True,
                    help=t('login_with_google_help')
                ):
                    st.session_state.selected_auth_method = "google"
                    st.rerun()

            elif provider == AuthProvider.GITHUB:
                if st.button(
                    "⚫ GitHub",
                    key="btn_github",
                    use_container_width=True,
                    help=t('login_with_github_help')
                ):
                    st.session_state.selected_auth_method = "github"
                    st.rerun()

            elif provider == AuthProvider.SIMPLE:
                if st.button(
                    "🔑 " + t('simple_password'),
                    key="btn_password",
                    use_container_width=True,
                    help=t('login_with_password_help')
                ):
                    st.session_state.selected_auth_method = "password"
                    st.rerun()

    # Afficher le formulaire selon la méthode choisie
    selected_method = st.session_state.get('selected_auth_method')

    if selected_method:
        st.markdown("---")

        # Bouton retour
        if st.button("← " + t('back_to_methods'), key="back_button"):
            st.session_state.selected_auth_method = None
            st.rerun()

        if selected_method == "password":
            _simple_auth(t)
        elif selected_method == "authentik":
            _authentik_auth(t)
        elif selected_method in ["google", "github"]:
            _oauth_auth(selected_method, t)

    st.stop()


def logout():
    """Déconnecte l'utilisateur."""
    # Supprimer la session persistante
    if 'persistent_session_id' in st.session_state:
        session_manager = get_session_manager()
        session_manager.delete_session(st.session_state['persistent_session_id'])

    # Nettoyer toutes les variables de session liées à l'authentification
    keys_to_remove = ['authenticated', 'auth_method', 'oauth_token', 'user_info', 'selected_auth_method', 'id_token', 'redirect_uri', 'persistent_session_id']
    for key in keys_to_remove:
        if key in st.session_state:
            del st.session_state[key]

    # Nettoyer les résultats OAuth stockés
    keys_to_clean = [k for k in st.session_state.keys() if k.endswith('_oauth_result')]
    for key in keys_to_clean:
        del st.session_state[key]

    st.rerun()


def get_user_info():
    """Retourne les informations de l'utilisateur connecté."""
    if st.session_state.get('authenticated', False):
        return st.session_state.get('user_info', {})
    return None


def show_user_widget(t):
    """
    Affiche un widget utilisateur dans la sidebar avec les infos de connexion.

    Args:
        t: Traducteur pour les messages
    """
    if st.session_state.get('authenticated', False):
        user_info = st.session_state.get('user_info', {})
        auth_method = st.session_state.get('auth_method', 'unknown')

        with st.sidebar:
            st.markdown("---")
            st.markdown(f"**👤 {user_info.get('name', 'User')}**")

            # Afficher l'email si disponible
            if user_info.get('email'):
                st.caption(f"📧 {user_info['email']}")

            if auth_method == "authentik":
                st.caption("🔐 " + "Connected via Authentik")
            elif auth_method == "google":
                st.caption("🔵 " + t('connected_via_google'))
            elif auth_method == "github":
                st.caption("⚫ " + t('connected_via_github'))
            elif auth_method == "password":
                st.caption("🔑 " + t('connected_via_password'))

            if st.button(t('logout_button'), key="logout_btn", use_container_width=True):
                logout()
