# ============================================================
# AZURE SQL DATABASE CONFIGURATION
# (Supports Azure Key Vault with automatic .env fallback)
# ============================================================
import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
load_dotenv()

# Import Key Vault / Secrets Manager
def get_secret(k, default=""):
    return os.getenv(k, default)

DB_CONFIG = {
    'driver': get_secret('DB_DRIVER', '{ODBC Driver 18 for SQL Server}'),
    'server': get_secret('DB_SERVER', 'threewaymatching.database.windows.net'),
    'database': get_secret('DB_NAME') or get_secret('DB_DATABASE', 'threewaymatching'),
    'uid': get_secret('DB_USERNAME') or get_secret('DB_UID', 'umarwani'),
    'pwd': get_secret('DB_PASSWORD') or get_secret('DB_PWD', 'Git@901#'),
    'trusted_connection': get_secret('DB_TRUSTED_CONNECTION', 'no'),
    'Encrypt': get_secret('DB_ENCRYPT', 'yes'),
    'TrustServerCertificate': get_secret('DB_TRUST_SERVER_CERTIFICATE', 'yes'),
    'Connection Timeout': 30
}

# Debug: Print config (hide password)
print(f"🔍 DB Config loaded:")
print(f"   Server: {DB_CONFIG['server']}")
print(f"   Database: {DB_CONFIG['database']}")
print(f"   Username: {DB_CONFIG['uid']}")
print(f"   Password: {'*' * len(DB_CONFIG['pwd']) if DB_CONFIG['pwd'] else 'NOT SET'}")
