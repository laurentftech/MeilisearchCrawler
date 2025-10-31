"""
Routes d'authentification pour l'API FastAPI.
Gère le login via Authentik et la génération de JWT.
"""

import logging
from datetime import timedelta
from typing import Optional
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel

from meilisearchcrawler.auth_config import get_auth_config, AuthProvider
from ..auth import jwt_handler, authentik_client

logger = logging.getLogger(__name__)

router = APIRouter()


class TokenResponse(BaseModel):
    """Réponse contenant le JWT."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfoResponse(BaseModel):
    """Informations utilisateur."""
    sub: str
    name: str
    email: str
    auth_method: str


@router.get("/auth/login")
async def login(redirect_uri: Optional[str] = Query(None, description="Optional redirect URI after login")):
    """
    Initie le flux d'authentification Authentik.

    Args:
        redirect_uri: URI de redirection après l'authentification (optionnel)

    Returns:
        Redirection vers Authentik pour l'authentification
    """
    auth_config = get_auth_config()

    # Vérifier si l'authentification est activée
    if not auth_config.is_enabled:
        raise HTTPException(status_code=400, detail="Authentication is disabled")

    # Vérifier si Authentik est configuré
    if not auth_config.has_provider(AuthProvider.AUTHENTIK):
        raise HTTPException(status_code=400, detail="Authentik authentication is not configured")

    config = auth_config.get_authentik_config()

    # URI de callback
    callback_uri = redirect_uri or os.getenv("AUTHENTIK_API_REDIRECT_URI", "http://localhost:8080/api/auth/callback")

    # Construire l'URL d'autorisation
    auth_params = {
        "client_id": config["client_id"],
        "redirect_uri": callback_uri,
        "response_type": "code",
        "scope": " ".join(config["scopes"]),
    }

    auth_url = f"{config['authorize_url']}?{urlencode(auth_params)}"

    return RedirectResponse(url=auth_url)


@router.get("/auth/callback")
async def callback(
    code: str = Query(..., description="Authorization code from Authentik"),
    redirect_uri: Optional[str] = Query(None, description="Optional redirect URI")
):
    """
    Callback OAuth2 depuis Authentik.
    Échange le code contre un access token et génère un JWT.

    Args:
        code: Code d'autorisation depuis Authentik
        redirect_uri: URI de redirection (optionnel)

    Returns:
        JWT pour accéder à l'API
    """
    auth_config = get_auth_config()

    if not auth_config.has_provider(AuthProvider.AUTHENTIK):
        raise HTTPException(status_code=400, detail="Authentik authentication is not configured")

    # URI de callback utilisée pour l'échange de code
    callback_uri = redirect_uri or os.getenv("AUTHENTIK_API_REDIRECT_URI", "http://localhost:8080/api/auth/callback")

    # Échanger le code contre un access token
    token_data = await authentik_client.exchange_code_for_token(code, callback_uri)

    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to exchange code for token")

    access_token = token_data.get("access_token")

    # Récupérer les informations utilisateur
    user_info = await authentik_client.get_user_info(access_token)

    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")

    # Créer un JWT pour notre API
    jwt_data = {
        "sub": user_info.get("sub"),
        "name": user_info.get("name", user_info.get("preferred_username", "User")),
        "email": user_info.get("email", ""),
        "auth_method": "authentik",
    }

    jwt_token = jwt_handler.create_access_token(jwt_data)

    # Retourner le JWT
    return TokenResponse(
        access_token=jwt_token,
        token_type="bearer",
        expires_in=auth_config.get_api_config()["jwt_expiration_minutes"] * 60
    )


@router.post("/auth/token")
async def get_token(username: str, password: str):
    """
    Obtenir un JWT via authentification simple (username/password).
    Utilisé uniquement si AUTH_PROVIDERS inclut 'simple'.

    Args:
        username: Nom d'utilisateur (ignoré pour l'instant)
        password: Mot de passe

    Returns:
        JWT pour accéder à l'API
    """
    auth_config = get_auth_config()

    # Vérifier si l'authentification simple est activée
    if not auth_config.has_provider(AuthProvider.SIMPLE):
        raise HTTPException(status_code=400, detail="Simple authentication is not configured")

    simple_password = auth_config.get_simple_password()

    # Vérifier le mot de passe
    if password != simple_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Créer un JWT
    jwt_data = {
        "sub": "dashboard_user",
        "name": username or "Dashboard User",
        "email": "",
        "auth_method": "simple",
    }

    jwt_token = jwt_handler.create_access_token(jwt_data)

    return TokenResponse(
        access_token=jwt_token,
        token_type="bearer",
        expires_in=auth_config.get_api_config()["jwt_expiration_minutes"] * 60
    )


@router.get("/auth/me", response_model=UserInfoResponse)
async def get_current_user_info(request: Request):
    """
    Récupère les informations de l'utilisateur authentifié.

    Returns:
        Informations utilisateur depuis le JWT
    """
    from ..auth import get_current_user
    from fastapi import Depends

    # Cette route nécessite l'authentification
    user = await get_current_user(request.headers.get("Authorization"))

    return UserInfoResponse(
        sub=user.get("sub", ""),
        name=user.get("name", ""),
        email=user.get("email", ""),
        auth_method=user.get("auth_method", "unknown")
    )


@router.post("/auth/logout")
async def logout():
    """
    Déconnexion (invalide le token côté client).
    Avec JWT, la déconnexion se fait côté client en supprimant le token.

    Returns:
        Message de confirmation
    """
    return {"message": "Logged out successfully. Please delete your access token."}


import os
