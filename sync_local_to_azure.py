"""
Script to copy / migrate all audit records from Local SQL Server to Azure SQL Database audit_logs.

Usage:
    python sync_local_to_azure.py [azure_server_name]
    Example:
    python sync_local_to_azure.py myserver.database.windows.net
"""
import sys
import os
import pyodbc
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load local environment
load_dotenv()

LOCAL_CONN_STR = os.getenv(
    "LOCAL_CONN_STR",
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-00TGE83\\SQLEXPRESS;DATABASE=threeway_matching;Trusted_Connection=yes;"
)

def get_best_odbc_driver():
    try:
        drivers = pyodbc.drivers()
        for d in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "ODBC Driver 13 for SQL Server", "SQL Server"]:
            if d in drivers:
                return f"{{{d}}}"
    except Exception:
        pass
    return "{ODBC Driver 18 for SQL Server}"


def migrate_to_azure(
    azure_server: str = "threewaymatching.database.windows.net", 
    db_name: str = "threewaymatching", 
    uid: str = "umarwani", 
    pwd: str = "Git@901#"
):
    azure_server = azure_server.strip() if azure_server else "threewaymatching.database.windows.net"


    driver = get_best_odbc_driver()
    
    # Format server
    server_str = f"tcp:{azure_server},1433" if not azure_server.startswith("tcp:") else azure_server
    
    azure_conn_str = (
        f"DRIVER={driver};SERVER={server_str};DATABASE={db_name};"
        f"UID={uid};PWD={pwd};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;"
    )

    print("=" * 70)
    print("🚀 COPYING AUDIT DATA: LOCAL SQL SERVER ➔ AZURE SQL DATABASE")
    print("=" * 70)
    print(f"📍 Local Source : DESKTOP-00TGE83\\SQLEXPRESS (threeway_matching)")
    print(f"📍 Azure Target : {azure_server} ({db_name})")
    print(f"👤 Azure User   : {uid}")
    print(f"🔧 ODBC Driver  : {driver}")
    print("-" * 70)

    # 1. Connect to Local DB
    print("\n[1/4] 🔌 Connecting to Local SQL Express...")
    try:
        local_conn = pyodbc.connect(LOCAL_CONN_STR, timeout=10)
        local_cur = local_conn.cursor()
        print("      ✅ Connected to Local DB successfully.")
    except Exception as e:
        print(f"      ❌ Local DB connection failed: {e}")
        return False

    # 2. Connect to Azure SQL DB
    print("\n[2/4] 🔌 Connecting to Azure SQL Database...")
    try:
        azure_conn = pyodbc.connect(azure_conn_str, timeout=30)
        azure_cur = azure_conn.cursor()
        print("      ✅ Connected to Azure SQL DB successfully.")
    except Exception as e:
        print(f"      ❌ Azure SQL connection failed: {e}")
        print("\n💡 Troubleshooting Tips:")
        print("   1. Verify your server name (e.g. server.database.windows.net)")
        print("   2. Check if your client IP is allowed in Azure SQL Firewall Rules in Azure Portal")
        print("   3. Confirm username and password")
        local_conn.close()
        return False

    # 3. Create tables in Azure if not existing
    print("\n[3/4] 🏗️ Creating / Verifying Azure tables (audit_logs, audit_statistics)...")
    try:
        azure_cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_logs')
            CREATE TABLE audit_logs (
                id INT IDENTITY(1,1) PRIMARY KEY,
                audit_id NVARCHAR(100) NOT NULL,
                event_type NVARCHAR(100) NOT NULL,
                severity NVARCHAR(50) NOT NULL,
                [user] NVARCHAR(100),
                action NVARCHAR(500),
                resource NVARCHAR(500),
                resource_type NVARCHAR(100),
                status NVARCHAR(50),
                error NVARCHAR(MAX),
                metadata NVARCHAR(MAX),
                raw_data NVARCHAR(MAX),
                inserted_at DATETIME DEFAULT GETDATE()
            )
        """)
        azure_cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_statistics')
            CREATE TABLE audit_statistics (
                id INT IDENTITY(1,1) PRIMARY KEY,
                run_id NVARCHAR(100),
                generated_at DATETIME,
                total_entries INT,
                info_count INT,
                warning_count INT,
                high_count INT,
                critical_count INT,
                status_success INT,
                status_failed INT,
                matching_status NVARCHAR(50),
                exception_count INT,
                hitl_case_id NVARCHAR(100),
                evidence_dir NVARCHAR(500),
                inserted_at DATETIME DEFAULT GETDATE()
            )
        """)
        azure_conn.commit()
        print("      ✅ Azure tables verified.")
    except Exception as e:
        print(f"      ⚠️ Table verification warning on Azure: {e}")

    # 4. Copy audit_logs
    print("\n[4/4] 📦 Migrating records to Azure audit_logs table...")
    try:
        local_cur.execute("""
            SELECT audit_id, event_type, severity, [user], action, resource, 
                   resource_type, status, error, metadata, raw_data, inserted_at 
            FROM audit_logs
            ORDER BY id ASC
        """)
        rows = local_cur.fetchall()
        total_local = len(rows)
        print(f"      📊 Found {total_local} records in local audit_logs.")

        migrated_count = 0
        skipped_count = 0

        for row in rows:
            audit_id = row[0]
            azure_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE audit_id = ?", (audit_id,))
            exists = azure_cur.fetchone()[0] > 0
            if not exists:
                azure_cur.execute("""
                    INSERT INTO audit_logs 
                    (audit_id, event_type, severity, [user], action, resource, resource_type, status, error, metadata, raw_data, inserted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(row))
                migrated_count += 1
            else:
                skipped_count += 1

        azure_conn.commit()
        print(f"      ✅ Migrated : {migrated_count} new records")
        print(f"      ⏩ Skipped  : {skipped_count} (already existing)")

        # Verify Azure count
        azure_cur.execute("SELECT COUNT(*) FROM audit_logs")
        final_count = azure_cur.fetchone()[0]
        print(f"\n🎉 Total rows in Azure SQL 'audit_logs' table: {final_count}")

    except Exception as e:
        print(f"      ❌ Error during audit_logs migration: {e}")

    # 5. Copy audit_statistics
    print("\n[5/5] 📊 Migrating records to Azure audit_statistics table...")
    try:
        local_cur.execute("""
            SELECT run_id, generated_at, total_entries, info_count, warning_count, high_count, critical_count,
                   status_success, status_failed, matching_status, exception_count, hitl_case_id, evidence_dir, inserted_at 
            FROM audit_statistics
            ORDER BY id ASC
        """)
        stat_rows = local_cur.fetchall()
        print(f"      📊 Found {len(stat_rows)} records in local audit_statistics.")

        migrated_stats = 0
        skipped_stats = 0

        for row in stat_rows:
            run_id = row[0]
            azure_cur.execute("SELECT COUNT(*) FROM audit_statistics WHERE run_id = ?", (run_id,))
            exists = azure_cur.fetchone()[0] > 0
            if not exists:
                azure_cur.execute("""
                    INSERT INTO audit_statistics 
                    (run_id, generated_at, total_entries, info_count, warning_count, high_count, critical_count,
                     status_success, status_failed, matching_status, exception_count, hitl_case_id, evidence_dir, inserted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(row))
                migrated_stats += 1
            else:
                skipped_stats += 1

        azure_conn.commit()
        print(f"      ✅ Migrated : {migrated_stats} new statistics records")
        print(f"      ⏩ Skipped  : {skipped_stats} (already existing)")

        # Verify Azure count
        azure_cur.execute("SELECT COUNT(*) FROM audit_statistics")
        final_stats_count = azure_cur.fetchone()[0]
        print(f"🎉 Total rows in Azure SQL 'audit_statistics' table: {final_stats_count}")

    except Exception as e:
        print(f"      ❌ Error during audit_statistics migration: {e}")

    local_conn.close()
    azure_conn.close()
    print("\n" + "=" * 70)
    print("✅ SYNC COMPLETED SUCCESSFULLY")

    print("=" * 70)
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        srv = sys.argv[1]
    else:
        # Prompt or check env
        srv = os.getenv("AZURE_DB_SERVER", "").strip()
        if not srv:
            srv = input("Enter your Azure SQL Server Name (e.g. your-server.database.windows.net): ").strip()
    
    migrate_to_azure(srv)
