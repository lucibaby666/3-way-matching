# ============================================================
# AZURE SQL DATABASE CONFIGURATION
# ============================================================
import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
load_dotenv()

DB_CONFIG = {
    'driver': os.getenv('DB_DRIVER', '{ODBC Driver 18 for SQL Server}'),
    'server': os.getenv('DB_SERVER', 'threewaymatching.database.windows.net'),
    'database': os.getenv('DB_NAME') or os.getenv('DB_DATABASE', 'threewaymatching'),
    'uid': os.getenv('DB_USERNAME') or os.getenv('DB_UID', 'umarwani'),
    'pwd': os.getenv('DB_PASSWORD') or os.getenv('DB_PWD', 'Git@901#'),
    'trusted_connection': os.getenv('DB_TRUSTED_CONNECTION', 'no'),
    'Encrypt': os.getenv('DB_ENCRYPT', 'yes'),
    'TrustServerCertificate': os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'yes')
}

# Debug: Print config (hide password)
print(f"🔍 DB Config loaded:")
print(f"   Server: {DB_CONFIG['server']}")
print(f"   Database: {DB_CONFIG['database']}")
print(f"   Username: {DB_CONFIG['uid']}")
print(f"   Password: {'*' * len(DB_CONFIG['pwd']) if DB_CONFIG['pwd'] else 'NOT SET'}")
