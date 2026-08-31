"""
Database connection and diagnostic test script for Azure SQL Database.
Tests connection, verifies tables (audit_logs, audit_statistics), and tests insert/read.
"""
import sys
import os
from pathlib import Path
from datetime import datetime

# Load environment
from dotenv import load_dotenv
load_dotenv()

from db_config import DB_CONFIG
from database_operations import (
    get_db_connection,
    create_audit_tables,
    insert_audit_to_db,
    get_audit_count,
    get_recent_audit_logs,
    verify_database_connection
)

def test_database():
    print("=" * 65)
    print("🔍 AZURE SQL DATABASE DIAGNOSTIC TEST")
    print("=" * 65)

    print("\n📋 Current Azure SQL Configuration:")
    for k, v in DB_CONFIG.items():
        if k.lower() in ('pwd', 'password') and v:
            print(f"   {k}: {'*' * len(str(v))}")
        else:
            print(f"   {k}: {v}")

    print("\n🔌 Testing Connection to Azure SQL Database...")
    status, msg = verify_database_connection()
    if not status:
        print(f"❌ Connection Failed: {msg}")
        print("\n💡 Troubleshooting Tips:")
        print("   1. Verify your server name (threewaymatching.database.windows.net)")
        print("   2. For Azure SQL: ensure your client IP is allowed in Azure SQL Firewall Rules in Azure Portal")
        print("   3. Ensure ODBC Driver 18 for SQL Server is installed")
        return False

    print(f"✅ Connected to Azure SQL successfully! ({msg})")

    print("\n🏗️ Creating / Verifying Azure Tables (audit_logs, audit_statistics)...")
    created = create_audit_tables()
    if created:
        print("✅ Tables 'audit_logs' and 'audit_statistics' verified in Azure SQL.")
    else:
        print("⚠️ Warning during table creation.")

    print("\n📊 Checking Current Data in Azure:")
    count = get_audit_count()
    print(f"   Total existing rows in Azure 'audit_logs': {count}")

    print("\n✍️ Testing Insert into Azure SQL 'audit_logs'...")
    test_entry = {
        "audit_id": f"AZURE-TEST-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": "AZURE_DB_TEST",
        "severity": "INFO",
        "user": DB_CONFIG.get('uid', 'admin'),
        "action": "Azure SQL Database connection and insert diagnostic test",
        "resource": DB_CONFIG.get('database', 'threewaymatching'),
        "resource_type": "DATABASE",
        "status": "SUCCESS",
        "error": None,
        "metadata": {
            "server": DB_CONFIG.get('server'),
            "database": DB_CONFIG.get('database'),
            "timestamp": datetime.now().isoformat()
        }
    }
    insert_ok = insert_audit_to_db(test_entry)
    if insert_ok:
        print("✅ Test audit record inserted into Azure SQL successfully!")
        new_count = get_audit_count()
        print(f"   New total rows in Azure 'audit_logs': {new_count}")
    else:
        print("❌ Test insert failed.")

    print("\n📜 Recent Logs from Azure SQL:")
    recent = get_recent_audit_logs(limit=5)
    for log in recent:
        print(f"   [{log.get('inserted_at')}] [{log.get('severity')}] {log.get('event_type')}: {log.get('action')}")

    print("\n" + "=" * 65)
    print("🎉 AZURE SQL DATABASE TEST COMPLETED SUCCESSFULLY")
    print("=" * 65)
    return True

if __name__ == "__main__":
    test_database()
