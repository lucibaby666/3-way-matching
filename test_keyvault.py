"""
Diagnostic & verification script for Azure Key Vault & Secrets Manager.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from secrets_manager import get_secret, _get_keyvault_client

def test_keyvault():
    print("=" * 65)
    print("🔐 AZURE KEY VAULT & SECRETS MANAGER DIAGNOSTIC")
    print("=" * 65)

    kv_name = os.getenv("KEY_VAULT_NAME", "").strip()
    kv_uri = os.getenv("KEY_VAULT_URI", "").strip()

    print("\n1. Key Vault Configuration:")
    print(f"   KEY_VAULT_NAME : {kv_name or '[Not set - using local .env fallback]'}")
    print(f"   KEY_VAULT_URI  : {kv_uri or (f'https://{kv_name}.vault.azure.net' if kv_name else '[None]')}")

    client = _get_keyvault_client()
    if client:
        print("   ✅ Azure Key Vault Client: CONNECTED")
    else:
        print("   ℹ️ Mode: Local .env Fallback Active")

    print("\n2. Testing Secret Resolution:")
    keys_to_test = [
        ("DB_SERVER", "Database Server"),
        ("DB_NAME", "Database Name"),
        ("DB_USERNAME", "Database Username"),
        ("DB_PASSWORD", "Database Password (masked)"),
        ("DOCUMENT_INTELLIGENCE_ENDPOINT", "Doc Intelligence Endpoint"),
    ]

    for key, label in keys_to_test:
        val = get_secret(key)
        if "password" in label.lower() or "key" in label.lower():
            display_val = "*" * len(val) if val else "[NOT SET]"
        else:
            display_val = val or "[NOT SET]"
        print(f"   🔑 {label:<32}: {display_val}")

    print("\n" + "=" * 65)
    print("🎉 SECRETS MANAGER READY")
    print("=" * 65)

if __name__ == "__main__":
    test_keyvault()
