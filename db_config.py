# ============================================================
# DATABASE CONFIGURATION
# ============================================================
import os

DB_CONFIG = {
    'driver': os.getenv('DB_DRIVER', '{ODBC Driver 17 for SQL Server}'),
    'server': os.getenv('DB_SERVER', 'DESKTOP-00TGE83\\SQLEXPRESS'),
    'database': os.getenv('DB_DATABASE', 'threeway_matching'),
    'trusted_connection': os.getenv('DB_TRUSTED_CONNECTION', 'yes'),
    'uid': os.getenv('DB_UID', ''),
    'pwd': os.getenv('DB_PWD', '')
}
