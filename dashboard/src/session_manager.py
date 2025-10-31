"""
Gestionnaire de session persistante pour l'authentification.
Utilise un cache en mémoire pour éviter la perte de session lors des reruns Streamlit.
"""

import streamlit as st
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import hashlib


class SessionManager:
    """Gestionnaire de sessions d'authentification persistantes."""

    def __init__(self):
        """Initialise le gestionnaire de sessions."""
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def create_session(self, email: str, user_info: Dict[str, Any], auth_method: str, token: Optional[Dict] = None) -> str:
        """
        Crée une nouvelle session d'authentification.

        Args:
            email: Email de l'utilisateur
            user_info: Informations utilisateur
            auth_method: Méthode d'authentification utilisée
            token: Token OAuth (optionnel)

        Returns:
            Session ID
        """
        # Générer un ID de session unique
        session_data = f"{email}_{auth_method}_{datetime.now().isoformat()}"
        session_id = hashlib.sha256(session_data.encode()).hexdigest()

        # Stocker les données de session
        self._sessions[session_id] = {
            "email": email,
            "user_info": user_info,
            "auth_method": auth_method,
            "token": token,
            "created_at": datetime.now(),
            "last_accessed": datetime.now(),
        }

        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les données d'une session.

        Args:
            session_id: ID de la session

        Returns:
            Données de session ou None si invalide/expirée
        """
        if session_id not in self._sessions:
            return None

        session = self._sessions[session_id]

        # Vérifier si la session a expiré (24 heures)
        if datetime.now() - session["created_at"] > timedelta(hours=24):
            del self._sessions[session_id]
            return None

        # Mettre à jour le dernier accès
        session["last_accessed"] = datetime.now()

        return session

    def delete_session(self, session_id: str):
        """
        Supprime une session.

        Args:
            session_id: ID de la session
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

    def cleanup_expired_sessions(self):
        """Nettoie les sessions expirées."""
        now = datetime.now()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session["created_at"] > timedelta(hours=24)
        ]
        for sid in expired:
            del self._sessions[sid]


@st.cache_resource
def get_session_manager() -> SessionManager:
    """Retourne l'instance globale du gestionnaire de sessions (cache persistant)."""
    return SessionManager()
