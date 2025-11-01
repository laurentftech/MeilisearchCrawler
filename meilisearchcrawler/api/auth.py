"""
Module d'authentification pour l'API FastAPI.
Supporte OpenID Connect (OIDC) et génération de JWT.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
import httpx
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from meilisearchcrawler.auth_config import get_auth_config, AuthProvider

logger = logging.getLogger(__name__)

# Security scheme pour JWT Bearer
security = HTTPBearer(auto_error=False)


class JWTHandler:
    """Gestionnaire de tokens JWT."""

    def __init__(self):
        self.auth_config = get_auth_config()
        self.api_config = self.auth_config.get_api_config()

    def create_access_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """
        Crée un token JWT.

        Args:
            data: Données à inclure dans le token (sub, email, name, etc.)
            expires_delta: Durée de validité du token

        Returns:
            Token JWT encodé
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.api_config["jwt_expiration_minutes"])

        to_encode.update({"exp": expire, "iat": datetime.utcnow()})

        encoded_jwt = jwt.encode(
            to_encode,
            self.api_config["jwt_secret"],
            algorithm=self.api_config["jwt_algorithm"]
        )

        return encoded_jwt

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Vérifie et décode un token JWT.

        Args:
            token: Token JWT à vérifier

        Returns:
            Payload du token si valide, None sinon
        """
        try:
            payload = jwt.decode(
                token,
                self.api_config["jwt_secret"],
                algorithms=[self.api_config["jwt_algorithm"]]
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.JWTError as e:
            logger.warning(f"JWT verification failed: {e}")
            return None


class OIDCClient:
    """Client pour l'authentification OpenID Connect (OIDC)."""

    def __init__(self):
        self.auth_config = get_auth_config()
        self.config = self.auth_config.get_oidc_config()

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
        """
        Échange un code d'autorisation contre un access token.

        Args:
            code: Code d'autorisation
            redirect_uri: URI de redirection

        Returns:
            Données du token (access_token, id_token, etc.) ou None en cas d'erreur
        """
        if not self.config:
            logger.error("OIDC is not configured")
            return None

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.config["token_url"],
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "client_id": self.config["client_id"],
                        "client_secret": self.config["client_secret"],
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                    return None

            except Exception as e:
                logger.error(f"Token exchange error: {e}")
                return None

    async def get_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations utilisateur depuis le provider OIDC.

        Args:
            access_token: Access token

        Returns:
            Informations utilisateur ou None en cas d'erreur
        """
        if not self.config:
            logger.error("OIDC is not configured")
            return None

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    self.config["userinfo_url"],
                    headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"User info fetch failed: {response.status_code}")
                    return None

            except Exception as e:
                logger.error(f"User info fetch error: {e}")
                return None

    async def verify_token(self, access_token: str) -> bool:
        """
        Vérifie la validité d'un access token en appelant l'API userinfo.

        Args:
            access_token: Access token à vérifier

        Returns:
            True si le token est valide, False sinon
        """
        user_info = await self.get_user_info(access_token)
        return user_info is not None


# Instances globales
jwt_handler = JWTHandler()
oidc_client = OIDCClient()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Dépendance FastAPI pour récupérer l'utilisateur actuel depuis le token JWT.

    Args:
        credentials: Credentials HTTP Bearer

    Returns:
        Informations utilisateur

    Raises:
        HTTPException: Si le token est invalide ou absent
    """
    auth_config = get_auth_config()

    # Si l'authentification est désactivée, retourner un utilisateur anonyme
    if not auth_config.is_enabled:
        return {"sub": "anonymous", "name": "Anonymous", "email": ""}

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = jwt_handler.verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[Dict[str, Any]]:
    """
    Dépendance FastAPI pour récupérer l'utilisateur actuel (optionnel).
    Ne lève pas d'exception si l'utilisateur n'est pas authentifié.

    Args:
        credentials: Credentials HTTP Bearer

    Returns:
        Informations utilisateur ou None
    """
    auth_config = get_auth_config()

    # Si l'authentification est désactivée, retourner un utilisateur anonyme
    if not auth_config.is_enabled:
        return {"sub": "anonymous", "name": "Anonymous", "email": ""}

    if not credentials:
        return None

    token = credentials.credentials
    payload = jwt_handler.verify_token(token)

    return payload
