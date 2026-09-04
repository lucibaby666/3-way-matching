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
            conn_str = f"DRIVER={DB_CONFIG['driver']};SERVER={DB_CONFIG['server']};DATABASE={DB_CONFIG['database']};UID={DB_CONFIG['uid']};PWD={DB_CONFIG['pwd']};Encrypt={encrypt};TrustServerCertificate={trust_cert};Connection Timeout=30;"
        
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


def create_persistence_tables():
    """Create persistence tables for sessions, runs, events, and HITL cases."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()

        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'upload_sessions')
            CREATE TABLE upload_sessions (
                upload_id NVARCHAR(100) PRIMARY KEY,
                storage_backend NVARCHAR(50) NOT NULL DEFAULT 'local',
                source_type NVARCHAR(50) NOT NULL DEFAULT 'upload',
                created_at DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)

        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'match_runs')
            CREATE TABLE match_runs (
                run_id NVARCHAR(100) PRIMARY KEY,
                upload_id NVARCHAR(100) NOT NULL,
                inject_discrepancy BIT NOT NULL DEFAULT 0,
                status NVARCHAR(50) NOT NULL DEFAULT 'pending',
                error NVARCHAR(MAX),
                result NVARCHAR(MAX),
                source_type NVARCHAR(50) NOT NULL DEFAULT 'upload',
                documents_json NVARCHAR(MAX),
                created_at DATETIME NOT NULL DEFAULT GETDATE(),
                finished_at DATETIME
            )
        """)

        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'match_run_events')
            CREATE TABLE match_run_events (
                id INT IDENTITY(1,1) PRIMARY KEY,
                run_id NVARCHAR(100) NOT NULL,
                event_type NVARCHAR(50) NOT NULL,
                event_data NVARCHAR(MAX) NOT NULL,
                seq INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_run_events_run_id' AND object_id = OBJECT_ID('match_run_events'))
            CREATE INDEX idx_run_events_run_id ON match_run_events(run_id)
        """)

        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'hitl_cases')
            CREATE TABLE hitl_cases (
                case_id NVARCHAR(100) PRIMARY KEY,
                run_id NVARCHAR(100),
                status NVARCHAR(50) NOT NULL DEFAULT 'PENDING',
                validation_result NVARCHAR(MAX),
                evidence NVARCHAR(MAX),
                reviewer NVARCHAR(100),
                decision_type NVARCHAR(50),
                decision_reason NVARCHAR(MAX),
                decision_comment NVARCHAR(MAX),
                decision_timestamp DATETIME,
                created_at DATETIME NOT NULL DEFAULT GETDATE()
            )
        """)

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Persistence table creation warning: {e}")
        logger.warning(f"Persistence table creation warning: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return False


def save_upload_session(upload_id: str, storage_backend: str = "local", source_type: str = "upload"):
    """Persist an upload session record."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM upload_sessions WHERE upload_id = ?)
            INSERT INTO upload_sessions (upload_id, storage_backend, source_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (upload_id, upload_id, storage_backend, source_type, datetime.now()))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save upload session: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_match_run(run_id: str, upload_id: str, inject_discrepancy: bool,
                   status: str = "pending", source_type: str = "upload",
                   documents_json: str = None):
    """Persist a match run record."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM match_runs WHERE run_id = ?)
            INSERT INTO match_runs (run_id, upload_id, inject_discrepancy, status, source_type, documents_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (run_id, upload_id, inject_discrepancy, status, source_type, documents_json, datetime.now()))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save match run: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_match_run_status(run_id: str, status: str, error: str = None, result: str = None):
    """Update match run status, optionally with error/result."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE match_runs
            SET status = ?, error = ?, result = ?, finished_at = CASE WHEN ? IN ('completed','failed') THEN GETDATE() ELSE finished_at END
            WHERE run_id = ?
        """, (status, error, result, status, run_id))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Failed to update match run status: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_match_run_event(run_id: str, event_type: str, event_data: str, seq: int = 0):
    """Persist a match run event (for SSE replay and history)."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO match_run_events (run_id, event_type, event_data, seq, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (run_id, event_type, event_data, seq, datetime.now()))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save match run event: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_match_run_events(run_id: str):
    """Get all events for a match run, ordered by sequence."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT event_type, event_data, seq, created_at
            FROM match_run_events
            WHERE run_id = ?
            ORDER BY seq ASC
        """, (run_id,))
        events = []
        for row in cursor.fetchall():
            events.append({
                "event_type": row[0],
                "event_data": row[1],
                "seq": row[2],
                "created_at": row[3],
            })
        cursor.close()
        return events
    except Exception as e:
        logger.error(f"Failed to get match run events: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_recent_runs(limit: int = 50):
    """Get recent match runs with summary info."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP (?)
                r.run_id, r.upload_id, r.status, r.source_type,
                r.inject_discrepancy, r.created_at, r.finished_at,
                r.error,
                (SELECT COUNT(*) FROM match_run_events e WHERE e.run_id = r.run_id AND e.event_type = 'step') as step_count,
                (SELECT COUNT(*) FROM hitl_cases h WHERE h.run_id = r.run_id) as hitl_case_count
            FROM match_runs r
            ORDER BY r.created_at DESC
        """, (limit,))
        runs = []
        for row in cursor.fetchall():
            runs.append({
                "run_id": row[0],
                "upload_id": row[1],
                "status": row[2],
                "source_type": row[3],
                "inject_discrepancy": row[4],
                "created_at": row[5],
                "finished_at": row[6],
                "error": row[7],
                "step_count": row[8],
                "hitl_case_count": row[9],
            })
        cursor.close()
        return runs
    except Exception as e:
        logger.error(f"Failed to get recent runs: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_run_detail(run_id: str):
    """Get full match run detail including result payload."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT run_id, upload_id, status, source_type, inject_discrepancy,
                   created_at, finished_at, error, result, documents_json
            FROM match_runs
            WHERE run_id = ?
        """, (run_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return None
        run = {
            "run_id": row[0],
            "upload_id": row[1],
            "status": row[2],
            "source_type": row[3],
            "inject_discrepancy": row[4],
            "created_at": row[5],
            "finished_at": row[6],
            "error": row[7],
            "result": row[8],
            "documents_json": row[9],
        }
        cursor.close()
        return run
    except Exception as e:
        logger.error(f"Failed to get run detail: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# HITL CASE PERSISTENCE
# ============================================================

def save_hitl_case(case_id: str, run_id: str, status: str,
                   validation_result_json: str, evidence_json: str):
    """Persist a new HITL case."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM hitl_cases WHERE case_id = ?)
            INSERT INTO hitl_cases (case_id, run_id, status, validation_result, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (case_id, case_id, run_id, status, validation_result_json, evidence_json, datetime.now()))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save HITL case: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_hitl_case_decision(case_id: str, status: str, reviewer: str,
                               decision_type: str, decision_reason: str,
                               decision_comment: str):
    """Update HITL case with human decision."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE hitl_cases
            SET status = ?, reviewer = ?, decision_type = ?,
                decision_reason = ?, decision_comment = ?, decision_timestamp = ?
            WHERE case_id = ?
        """, (status, reviewer, decision_type, decision_reason, decision_comment, datetime.now(), case_id))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Failed to update HITL case decision: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_hitl_case(case_id: str):
    """Get a single HITL case."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, run_id, status, validation_result, evidence,
                   reviewer, decision_type, decision_reason, decision_comment,
                   decision_timestamp, created_at
            FROM hitl_cases
            WHERE case_id = ?
        """, (case_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return None
        case = {
            "case_id": row[0],
            "run_id": row[1],
            "status": row[2],
            "validation_result": row[3],
            "evidence": row[4],
            "reviewer": row[5],
            "decision_type": row[6],
            "decision_reason": row[7],
            "decision_comment": row[8],
            "decision_timestamp": row[9],
            "created_at": row[10],
        }
        cursor.close()
        return case
    except Exception as e:
        logger.error(f"Failed to get HITL case: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_pending_hitl_cases():
    """Get all pending HITL cases."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, run_id, status, created_at
            FROM hitl_cases
            WHERE status = 'PENDING'
            ORDER BY created_at DESC
        """)
        cases = []
        for row in cursor.fetchall():
            cases.append({
                "case_id": row[0],
                "run_id": row[1],
                "status": row[2],
                "created_at": row[3],
            })
        cursor.close()
        return cases
    except Exception as e:
        logger.error(f"Failed to get pending HITL cases: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_recent_audit_logs(limit=100):
    """Get recent audit logs"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP ? 
                audit_id, event_type, severity, [user], action, 
                status, inserted_at
            FROM audit_logs
            ORDER BY inserted_at DESC
        """, (limit,))
        
        logs = []
        for row in cursor.fetchall():
            logs.append({
                'audit_id': row[0],
                'event_type': row[1],
                'severity': row[2],
                'user': row[3],
                'action': row[4],
                'status': row[5],
                'inserted_at': row[6]
            })
        
        cursor.close()
        conn.close()
        return logs
    except Exception as e:
        print(f"⚠️ Failed to get audit logs: {e}")
        conn.close()
        return []