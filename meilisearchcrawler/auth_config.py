"""
Configuration centralisée pour l'authentification.
Supporte Authentik (OpenID Connect), Google OAuth, GitHub OAuth et authentification simple.
"""

import os
from typing import Optional, List, Dict, Any
from enum import Enum


class AuthProvider(Enum):
    """Fournisseurs d'authentification disponibles."""
    AUTHENTIK = "authentik"
    GOOGLE = "google"
    GITHUB = "github"
    SIMPLE = "simple"
    NONE = "none"  # Pas d'authentification


class AuthConfig:
    """Configuration de l'authentification basée sur les variables d'environnement."""

    def __init__(self):
        """Initialise la configuration depuis les variables d'environnement."""
        # Désactiver complètement l'authentification
        self.auth_disabled = os.getenv("AUTH_DISABLED", "false").lower() == "true"

        if self.auth_disabled:
            self.enabled_providers = [AuthProvider.NONE]
            return

        # Lire la liste des providers activés depuis la variable d'environnement
        # Format: "authentik,simple" ou "google,github,simple"
        enabled_str = os.getenv("AUTH_PROVIDERS", "").strip().lower()

        if enabled_str:
            # Utiliser la configuration explicite
            provider_names = [p.strip() for p in enabled_str.split(",") if p.strip()]
            self.enabled_providers = []

            for name in provider_names:
                try:
                    self.enabled_providers.append(AuthProvider(name))
                except ValueError:
                    print(f"Warning: Unknown auth provider '{name}' in AUTH_PROVIDERS")
        else:
            # Auto-détection basée sur les variables d'environnement disponibles
            self.enabled_providers = self._detect_providers()

    def _detect_providers(self) -> List[AuthProvider]:
        """Détecte automatiquement les providers configurés."""
        providers = []

        # Authentik (priorité la plus haute)
        if self._is_authentik_configured():
            providers.append(AuthProvider.AUTHENTIK)

        # Google OAuth
        if self._is_google_configured():
            providers.append(AuthProvider.GOOGLE)

        # GitHub OAuth
        if self._is_github_configured():
            providers.append(AuthProvider.GITHUB)

        # Simple password
        if self._is_simple_configured():
            providers.append(AuthProvider.SIMPLE)

        # Si aucun provider n'est configuré, désactiver l'auth
        if not providers:
            providers.append(AuthProvider.NONE)

        return providers

    def _is_authentik_configured(self) -> bool:
        """Vérifie si Authentik est configuré."""
        return all([
            os.getenv("AUTHENTIK_CLIENT_ID"),
            os.getenv("AUTHENTIK_CLIENT_SECRET"),
            os.getenv("AUTHENTIK_DOMAIN")
        ])

    def _is_google_configured(self) -> bool:
        """Vérifie si Google OAuth est configuré."""
        return all([
            os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
            os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
        ])

    def _is_github_configured(self) -> bool:
        """Vérifie si GitHub OAuth est configuré."""
        return all([
            os.getenv("GITHUB_OAUTH_CLIENT_ID"),
            os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
        ])

    def _is_simple_configured(self) -> bool:
        """Vérifie si l'authentification simple est configurée."""
        return bool(os.getenv("DASHBOARD_PASSWORD"))

    @property
    def is_enabled(self) -> bool:
        """Retourne True si l'authentification est activée."""
        return not self.auth_disabled and AuthProvider.NONE not in self.enabled_providers

    @property
    def providers(self) -> List[AuthProvider]:
        """Retourne la liste des providers activés."""
        return self.enabled_providers

    def has_provider(self, provider: AuthProvider) -> bool:
        """Vérifie si un provider est activé."""
        return provider in self.enabled_providers

    # --- Configuration Authentik ---

    def get_authentik_config(self) -> Optional[Dict[str, str]]:
        """Retourne la configuration Authentik."""
        if not self.has_provider(AuthProvider.AUTHENTIK):
            return None

        domain = os.getenv("AUTHENTIK_DOMAIN", "").strip()

        # Nettoyer le domaine (enlever les slashes et protocole)
        domain = domain.rstrip("/").replace("https://", "").replace("http://", "")

        return {
            "client_id": os.getenv("AUTHENTIK_CLIENT_ID", ""),
            "client_secret": os.getenv("AUTHENTIK_CLIENT_SECRET", ""),
            "domain": domain,
            "server_metadata_url": f"https://{domain}/application/o/{os.getenv('AUTHENTIK_APP_SLUG', 'kidsearch')}/.well-known/openid-configuration",
            "authorize_url": f"https://{domain}/application/o/authorize/",
            "token_url": f"https://{domain}/application/o/token/",
            "userinfo_url": f"https://{domain}/application/o/userinfo/",
            "scopes": os.getenv("AUTHENTIK_SCOPES", "openid profile email").split(),
        }

    # --- Configuration Google OAuth ---

    def get_google_config(self) -> Optional[Dict[str, str]]:
        """Retourne la configuration Google OAuth."""
        if not self.has_provider(AuthProvider.GOOGLE):
            return None

        return {
            "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "redirect_uri": os.getenv("GOOGLE_OAUTH_REDIRECT_URI", ""),
            "authorize_url": os.getenv("GOOGLE_OAUTH_AUTHORIZE_URL", "https://accounts.google.com/o/oauth2/v2/auth"),
            "token_url": os.getenv("GOOGLE_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token"),
            "scopes": "openid profile email",
        }

    # --- Configuration GitHub OAuth ---

    def get_github_config(self) -> Optional[Dict[str, str]]:
        """Retourne la configuration GitHub OAuth."""
        if not self.has_provider(AuthProvider.GITHUB):
            return None

        return {
            "client_id": os.getenv("GITHUB_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("GITHUB_OAUTH_CLIENT_SECRET", ""),
            "redirect_uri": os.getenv("GITHUB_OAUTH_REDIRECT_URI", ""),
            "authorize_url": os.getenv("GITHUB_OAUTH_AUTHORIZE_URL", "https://github.com/login/oauth/authorize"),
            "token_url": os.getenv("GITHUB_OAUTH_TOKEN_URL", "https://github.com/login/oauth/access_token"),
            "scopes": "read:user user:email",
        }

    # --- Configuration Simple Password ---

    def get_simple_password(self) -> Optional[str]:
        """Retourne le mot de passe pour l'authentification simple."""
        if not self.has_provider(AuthProvider.SIMPLE):
            return None
        return os.getenv("DASHBOARD_PASSWORD", "")

    # --- Email Whitelist ---

    def get_allowed_emails(self) -> Optional[List[str]]:
        """Retourne la liste des emails autorisés pour OAuth (None = tous autorisés)."""
        allowed_emails_str = os.getenv("ALLOWED_EMAILS", "").strip()

        if not allowed_emails_str:
            return None  # Aucune restriction

        # Parse la liste d'emails (séparés par des virgules)
        emails = [email.strip().lower() for email in allowed_emails_str.split(",") if email.strip()]

        return emails if emails else None

    def is_email_allowed(self, email: str) -> bool:
        """Vérifie si un email est autorisé à se connecter."""
        if not email:
            return False

        allowed_emails = self.get_allowed_emails()

        # Si aucune restriction configurée, tous les emails sont autorisés
        if allowed_emails is None:
            return True

        # Vérifier si l'email est dans la liste
        return email.strip().lower() in allowed_emails

    # --- Configuration API ---

    def get_api_config(self) -> Dict[str, Any]:
        """Retourne la configuration pour l'API FastAPI."""
        return {
            "jwt_secret": os.getenv("JWT_SECRET_KEY", "change-me-in-production"),
            "jwt_algorithm": os.getenv("JWT_ALGORITHM", "HS256"),
            "jwt_expiration_minutes": int(os.getenv("JWT_EXPIRATION_MINUTES", "1440")),  # 24h par défaut
        }


# Instance globale
_auth_config: Optional[AuthConfig] = None


def get_auth_config() -> AuthConfig:
    """Retourne l'instance globale de la configuration d'authentification."""
    global _auth_config
    if _auth_config is None:
        _auth_config = AuthConfig()
    return _auth_config
