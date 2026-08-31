import os
import logging
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

# Load .env if present (optional, for non‑Azure secrets)
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.is_file():
    load_dotenv(dotenv_path=env_path)

logger = logging.getLogger("ThreeWayMatching.SecretsManager")

# In‑memory cache for secrets
_SECRETS_CACHE: Dict[str, str] = {}

# Azure Key Vault client – lazily initialized
_KV_CLIENT: Optional[object] = None
_KV_INITIALIZED = False


def _normalize_secret_name(name: str) -> str:
    """Convert a secret name to Azure Key Vault format (lower‑case, dashes)."""
    return name.replace("_", "-").lower()


def _get_keyvault_client() -> Optional[object]:
    """Create and return an Azure Key Vault SecretClient if Vault details are present.

    Looks for ``KEY_VAULT_NAME`` or ``KEY_VAULT_URI`` environment variables.
    Returns ``None`` when the vault is not configured or the Azure SDK is unavailable.
    """
    global _KV_CLIENT, _KV_INITIALIZED
    if _KV_INITIALIZED:
        return _KV_CLIENT
    _KV_INITIALIZED = True
    vault_name = os.getenv("KEY_VAULT_NAME", "").strip()
    vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
    # Build URI from name if only name is provided
    if not vault_uri and vault_name:
        vault_uri = f"https://{vault_name}.vault.azure.net"
    if not vault_uri:
        logger.debug("Azure Key Vault not configured – falling back to environment variables.")
        return None
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError:
        logger.info("Azure SDK not installed – using .env fallback.")
        return None
    try:
        credential = DefaultAzureCredential()
        _KV_CLIENT = SecretClient(vault_url=vault_uri, credential=credential)
        logger.info(f"Connected to Azure Key Vault: {vault_uri}")
        return _KV_CLIENT
    except Exception as exc:
        logger.warning(f"Failed to initialise Azure Key Vault client: {exc}. Using env fallback.")
        return None


def get_secret(secret_name: str, default: str = "") -> str:
    """Retrieve a secret value.

    Order of precedence:
    1. In‑memory cache
    2. Azure Key Vault (if configured and accessible)
    3. Environment variable (including .env)
    4. Default value
    """
    if not secret_name:
        return default
    # Normalise name for KV look‑up
    kv_name = _normalize_secret_name(secret_name)
    # 1. Cache
    if secret_name in _SECRETS_CACHE:
        return _SECRETS_CACHE[secret_name]
    # 2. Azure Key Vault
    client = _get_keyvault_client()
    if client:
        try:
            kv_secret = client.get_secret(kv_name)
            value = kv_secret.value
            _SECRETS_CACHE[secret_name] = value
            return value
        except Exception as exc:
            logger.debug(f"Key Vault secret '{kv_name}' not found or error: {exc}")
            # fall through to env
    # 3. Environment variable (including .env)
    value = os.getenv(secret_name, default)
    _SECRETS_CACHE[secret_name] = value
    return value

# Compatibility stub (some legacy imports expect this name)
def _get_keyvault_client_stub() -> None:
    return None
