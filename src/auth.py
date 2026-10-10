"""
auth.py
=======
Autenticación OAuth2 contra Copernicus Data Space Ecosystem.
Reutiliza el token mientras sea válido; NO solicita uno nuevo por cada petición.

Soporta HTTP_PROXY / HTTPS_PROXY / NO_PROXY automáticamente
(variables de entorno estándar que requests lee por defecto).
"""
import os
import time
import logging
from typing import Optional

import requests
from sentinelhub import SHConfig

from .config import get_sh_credentials


logger = logging.getLogger(__name__)


TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_BASE_URL = "https://sh.dataspace.copernicus.eu"
TOKEN_EXPIRY_MARGIN_SECONDS = 60


def _proxy_info() -> dict:
    """Lee variables de proxy de entorno. Devuelve dict informativo."""
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"]
    info = {k: os.environ.get(k) for k in keys if os.environ.get(k)}
    return info


class CopernicusAuth:
    """Gestor de autenticación con cache de token."""

    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise ValueError("Client ID y Client Secret son obligatorios.")
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._token_type: str = "Bearer"
        self._last_sh_config: Optional[SHConfig] = None

    # ----- internals -----
    def _token_is_valid(self) -> bool:
        if self._access_token is None:
            return False
        return time.time() < (self._expires_at - TOKEN_EXPIRY_MARGIN_SECONDS)

    def _request_new_token(self) -> None:
        logger.info("Solicitando nuevo token OAuth2 a Copernicus...")
        proxy_env = _proxy_info()
        if proxy_env:
            logger.info("Detectadas variables proxy: %s",
                        ", ".join(f"{k}=***" for k in proxy_env.keys()))

        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            resp = requests.post(TOKEN_URL, data=data, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as e:
            detail = e.response.text[:500] if e.response is not None else str(e)
            logger.error(
                "Error HTTP solicitando token (%s): %s",
                getattr(e.response, "status_code", "?"),
                detail,
            )
            raise
        except requests.RequestException as e:
            logger.error("Error de red solicitando token: %s", e)
            if "NameResolutionError" in str(type(e).__name__):
                logger.error(
                    "  Causa probable: FALLO DNS. Soluciones: "
                    "1) Configurar variables HTTP_PROXY/HTTPS_PROXY "
                    "2) Cambiar DNS a 8.8.8.8/1.1.1.1 "
                    "3) Desconectar VPN/firewall si bloquea Copernicus."
                )
            raise

        payload = resp.json()
        access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 0))
        token_type = payload.get("token_type", "Bearer")

        if not access_token:
            raise RuntimeError(
                f"Respuesta de token inválida: no se encontró access_token. "
                f"Claves recibidas: {sorted(payload.keys())}"
            )

        self._access_token = access_token
        self._token_type = token_type
        self._expires_at = time.time() + expires_in
        self._last_sh_config = None
        remaining = max(0, int(self._expires_at - time.time()))
        logger.info("Token obtenido. Expira en ~%d segundos (%d min).", remaining, remaining // 60)

    # ----- public API -----
    @property
    def access_token(self) -> str:
        if not self._token_is_valid():
            self._request_new_token()
        return self._access_token  # type: ignore[return-value]

    @property
    def token_type(self) -> str:
        _ = self.access_token
        return self._token_type

    def get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"{self.token_type} {self.access_token}"}

    def get_sh_config(self) -> SHConfig:
        """Devuelve un SHConfig listo para usar con sentinelhub (apuntando a Copernicus Dataspace."""
        if self._last_sh_config is not None and self._token_is_valid():
            return self._last_sh_config
        cfg = SHConfig()
        cfg.sh_client_id = self._client_id
        cfg.sh_client_secret = self._client_secret
        cfg.sh_base_url = SH_BASE_URL
        cfg.sh_token_url = TOKEN_URL
        self._last_sh_config = cfg
        return cfg


_default_auth: Optional[CopernicusAuth] = None


def get_auth() -> CopernicusAuth:
    """Singleton perezoso: reutiliza la misma instancia en todo el pipeline."""
    global _default_auth
    if _default_auth is None:
        client_id, client_secret = get_sh_credentials()
        _default_auth = CopernicusAuth(client_id, client_secret)
    return _default_auth


def reset_auth() -> None:
    """Obliga a pedir un token nuevo en la siguiente petición (útil en tests)."""
    global _default_auth
    _default_auth = None
