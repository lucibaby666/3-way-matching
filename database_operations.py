# database_operations.py
import json
import pyodbc
from datetime import datetime
import logging

# Setup logger for database operations
logger = logging.getLogger("ThreeWayMatching")

# Import database configuration
try:
    from db_config import DB_CONFIG
except ImportError:
    DB_CONFIG = {
        'driver': '{ODBC Driver 17 for SQL Server}',
        'server': 'DESKTOP-00TGE83\\SQLEXPRESS',
        'database': 'threeway_matching',
        'trusted_connection': 'yes'
    }


def get_db_connection():
    """Get SQL Server / Azure SQL database connection"""
    try:
        if DB_CONFIG.get('trusted_connection') == 'yes':
            conn_str = f"DRIVER={DB_CONFIG['driver']};SERVER={DB_CONFIG['server']};DATABASE={DB_CONFIG['database']};Trusted_Connection=yes;"
        else:
            encrypt = DB_CONFIG.get('Encrypt', DB_CONFIG.get('encrypt', 'yes'))
            trust_cert = DB_CONFIG.get('TrustServerCertificate', DB_CONFIG.get('trust_server_certificate', 'yes'))
            conn_str = f"DRIVER={DB_CONFIG['driver']};SERVER={DB_CONFIG['server']};DATABASE={DB_CONFIG['database']};UID={DB_CONFIG['uid']};PWD={DB_CONFIG['pwd']};Encrypt={encrypt};TrustServerCertificate={trust_cert};"
        
        connection = pyodbc.connect(conn_str, timeout=30)
        return connection
    except Exception as e:
        print(f"⚠️ Database connection failed: {e}")
        logger.error(f"Database connection failed: {e}")
        return None



def create_audit_tables():
    """Create audit tables if they don't exist"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # Create audit_logs table
        cursor.execute("""
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
        
        # Alter existing table columns if needed
        cursor.execute("""
            IF EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_logs')
            BEGIN
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN audit_id NVARCHAR(100)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN event_type NVARCHAR(100)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN [user] NVARCHAR(100)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN action NVARCHAR(500)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN resource NVARCHAR(500)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN resource_type NVARCHAR(100)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
                BEGIN TRY
                    ALTER TABLE audit_logs ALTER COLUMN status NVARCHAR(50)
                END TRY
                BEGIN CATCH
                    -- Column might not exist or already has correct type
                END CATCH
            END
        """)
        
        # Create audit_statistics table
        cursor.execute("""
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
        
        # Add missing columns to audit_statistics if it was created previously with older schema
        cursor.execute("""
            IF EXISTS (SELECT * FROM sys.tables WHERE name = 'audit_statistics')
            BEGIN
                IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('audit_statistics') AND name = 'matching_status')
                    ALTER TABLE audit_statistics ADD matching_status NVARCHAR(50);
                IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('audit_statistics') AND name = 'exception_count')
                    ALTER TABLE audit_statistics ADD exception_count INT;
                IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('audit_statistics') AND name = 'hitl_case_id')
                    ALTER TABLE audit_statistics ADD hitl_case_id NVARCHAR(100);
                IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('audit_statistics') AND name = 'evidence_dir')
                    ALTER TABLE audit_statistics ADD evidence_dir NVARCHAR(500);
                IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('audit_statistics') AND name = 'inserted_at')
                    ALTER TABLE audit_statistics ADD inserted_at DATETIME DEFAULT GETDATE();
            END
        """)
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Table creation warning: {e}")
        logger.warning(f"Table creation warning: {e}")
        conn.close()
        return True



def insert_audit_to_db(audit_entry):
    """Insert an audit entry into the database"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False
        
        cursor = conn.cursor()
        
        metadata_json = json.dumps(audit_entry.get('metadata', {}))
        raw_data_json = json.dumps(audit_entry)
        
        cursor.execute("""
            INSERT INTO audit_logs 
            (audit_id, event_type, severity, [user], action, 
             resource, resource_type, status, error, metadata, raw_data, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(audit_entry.get('audit_id', ''))[:100],
            str(audit_entry.get('event_type', ''))[:100],
            str(audit_entry.get('severity', 'INFO'))[:50],
            str(audit_entry.get('user', 'system'))[:100],
            str(audit_entry.get('action', ''))[:500],
            str(audit_entry.get('resource', ''))[:500],
            str(audit_entry.get('resource_type', ''))[:100],
            str(audit_entry.get('status', 'SUCCESS'))[:50],
            str(audit_entry.get('error', '')) if audit_entry.get('error') else None,
            metadata_json,
            raw_data_json,
            datetime.now()
        ))
        
        conn.commit()
        cursor.close()
        return True
        
    except Exception as e:
        print(f"⚠️ Failed to insert audit: {e}")
        logger.error(f"Failed to insert audit: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def insert_statistics_to_db(stats):
    """Insert statistics into the database"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        run_id = f"RUN-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        cursor.execute("""
            INSERT INTO audit_statistics 
            (run_id, generated_at, total_entries, info_count, warning_count, high_count, critical_count,
             status_success, status_failed, matching_status, exception_count, hitl_case_id, evidence_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            datetime.now(),
            stats.get('total_entries', 0),
            stats.get('severity_counts', {}).get('INFO', 0),
            stats.get('severity_counts', {}).get('WARNING', 0),
            stats.get('severity_counts', {}).get('HIGH', 0),
            stats.get('severity_counts', {}).get('CRITICAL', 0),
            stats.get('status_counts', {}).get('SUCCESS', 0),
            stats.get('status_counts', {}).get('FAILED', 0),
            stats.get('matching_status', 'UNKNOWN'),
            stats.get('exception_count', 0),
            stats.get('hitl_case_id', None),
            stats.get('evidence_dir', '')
        ))
        
        conn.commit()
        conn.close()
        return run_id
    except Exception as e:
        # Try self-healing schema migration once
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        try:
            create_audit_tables()
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO audit_statistics 
                    (run_id, generated_at, total_entries, info_count, warning_count, high_count, critical_count,
                     status_success, status_failed, matching_status, exception_count, hitl_case_id, evidence_dir)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    datetime.now(),
                    stats.get('total_entries', 0),
                    stats.get('severity_counts', {}).get('INFO', 0),
                    stats.get('severity_counts', {}).get('WARNING', 0),
                    stats.get('severity_counts', {}).get('HIGH', 0),
                    stats.get('severity_counts', {}).get('CRITICAL', 0),
                    stats.get('status_counts', {}).get('SUCCESS', 0),
                    stats.get('status_counts', {}).get('FAILED', 0),
                    stats.get('matching_status', 'UNKNOWN'),
                    stats.get('exception_count', 0),
                    stats.get('hitl_case_id', None),
                    stats.get('evidence_dir', '')
                ))
                conn.commit()
                conn.close()
                return run_id
        except Exception as retry_err:
            print(f"⚠️ Failed to insert statistics: {retry_err}")
            logger.error(f"Failed to insert statistics: {retry_err}")
        return None



def verify_database_connection():
    """Verify database connection and return status"""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()
            cursor.close()
            conn.close()
            return True, "Connected successfully"
        except Exception as e:
            conn.close()
            return False, str(e)
    return False, "Connection failed"


def get_audit_count():
    """Get total count of audit logs"""
    conn = get_db_connection()
    if not conn:
        return 0
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return count
    except Exception as e:
        print(f"⚠️ Failed to get audit count: {e}")
        conn.close()
        return 0


def get_recent_audit_logs(limit=200, severity=None, event_type=None, search=None):
    """Get recent audit logs with optional filters"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        query = """
            SELECT TOP (?) 
                audit_id, event_type, severity, [user], action, 
                resource, resource_type, status, error, metadata, inserted_at
            FROM audit_logs
            WHERE 1=1
        """
        params = [int(limit)]
        if severity and severity.upper() != 'ALL':
            query += " AND UPPER(severity) = ?"
            params.append(severity.upper())
        if event_type and event_type.upper() != 'ALL':
            query += " AND UPPER(event_type) = ?"
            params.append(event_type.upper())
        if search:
            query += " AND (action LIKE ? OR audit_id LIKE ? OR resource LIKE ? OR [user] LIKE ? OR error LIKE ?)"
            s_param = f"%{search}%"
            params.extend([s_param, s_param, s_param, s_param, s_param])
            
        query += " ORDER BY inserted_at DESC"
        
        cursor.execute(query, params)
        
        logs = []
        for row in cursor.fetchall():
            meta = row[9]
            if meta and isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    pass
            logs.append({
                'audit_id': row[0],
                'event_type': row[1],
                'severity': row[2],
                'user': row[3] or 'system',
                'action': row[4] or '',
                'resource': row[5] or '',
                'resource_type': row[6] or '',
                'status': row[7] or 'SUCCESS',
                'error': row[8],
                'metadata': meta or {},
                'inserted_at': row[10].isoformat() if hasattr(row[10], 'isoformat') else str(row[10]),
                'source': 'database'
            })
        
        cursor.close()
        conn.close()
        return logs
    except Exception as e:
        print(f"⚠️ Failed to get audit logs: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return []