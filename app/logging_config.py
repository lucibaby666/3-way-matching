
import logging
import json
import datetime
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Dict, List, Any, Optional


# ============================================================
# LOGGING CONFIGURATION
# ============================================================

class AuditSeverity(Enum):
    """Audit severity levels"""
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"


@dataclass
class AuditEntry:
    """Complete audit entry for tracking all system actions"""
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    event_type: str = ""
    severity: str = "INFO"
    user: str = "system"
    action: str = ""
    resource: str = ""
    resource_type: str = ""
    old_value: Any = None
    new_value: Any = None
    changes: Dict = field(default_factory=dict)
    status: str = "SUCCESS"
    error: str = ""
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        for key, value in result.items():
            if hasattr(value, '__dict__'):
                result[key] = str(value)
            elif isinstance(value, Enum):
                result[key] = value.value
        return result


class AuditLogger:
    """
    Complete audit logging system with tracking capabilities.
    Logs all system actions with severity levels and metadata.
    """
    
    def __init__(self, log_dir: str = "./logs", name: str = "ThreeWayMatching"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.name = name
        
        # Setup logger
        self.logger = self._setup_logger()
        
        # Audit file
        self.audit_file = self.log_dir / f"audit_{datetime.datetime.now().strftime('%Y%m%d')}.json"
        self.entries: List[AuditEntry] = []
        self._load_existing_entries()
    
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(self.name)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        
        # File handler for all logs
        log_file = self.log_dir / f"{self.name.lower()}_{datetime.datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # File handler for errors only
        error_file = self.log_dir / f"errors_{datetime.datetime.now().strftime('%Y%m%d')}.log"
        error_handler = logging.FileHandler(error_file, encoding='utf-8')
        error_handler.setLevel(logging.ERROR)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        error_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(error_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def _load_existing_entries(self):
        if self.audit_file.exists():
            try:
                with open(self.audit_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for entry in data.get('entries', []):
                        self.entries.append(AuditEntry(**entry))
            except Exception as e:
                self.logger.error(f"Failed to load audit entries: {e}")
    
    def log(self, 
            event_type: str,
            action: str,
            severity: AuditSeverity = AuditSeverity.INFO,
            resource: str = "",
            resource_type: str = "",
            old_value: Any = None,
            new_value: Any = None,
            changes: Dict = None,
            status: str = "SUCCESS",
            error: str = "",
            metadata: Dict = None) -> str:
        
        entry = AuditEntry(
            audit_id=str(uuid.uuid4())[:8],
            timestamp=datetime.datetime.now().isoformat(),
            event_type=event_type,
            severity=severity.value,
            user="system",
            action=action,
            resource=resource,
            resource_type=resource_type,
            old_value=old_value,
            new_value=new_value,
            changes=changes or {},
            status=status,
            error=error,
            metadata=metadata or {}
        )
        
        self.entries.append(entry)
        self._save_audit_entry(entry)
        
        # Log to standard logger
        log_msg = f"{event_type} - {action} - {status}"
        if severity == AuditSeverity.CRITICAL:
            self.logger.critical(log_msg)
        elif severity == AuditSeverity.HIGH:
            self.logger.error(log_msg)
        elif severity == AuditSeverity.WARNING or severity == AuditSeverity.MEDIUM:
            self.logger.warning(log_msg)
        else:
            self.logger.info(log_msg)
        
        return entry.audit_id
    
    def _save_audit_entry(self, entry: AuditEntry):
        try:
            if self.audit_file.exists():
                with open(self.audit_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {'entries': [], 'statistics': {}}
            
            data['entries'].append(entry.to_dict())
            
            # Update statistics
            stats = data.get('statistics', {})
            stats['total_entries'] = len(data['entries'])
            stats['last_updated'] = datetime.datetime.now().isoformat()
            
            event_type = entry.event_type
            stats['event_types'] = stats.get('event_types', {})
            stats['event_types'][event_type] = stats['event_types'].get(event_type, 0) + 1
            
            severity = entry.severity
            stats['severity'] = stats.get('severity', {})
            stats['severity'][severity] = stats['severity'].get(severity, 0) + 1
            
            data['statistics'] = stats
            
            with open(self.audit_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
                
        except Exception as e:
            self.logger.error(f"Error saving audit entry: {e}")
    
    def get_statistics(self) -> Dict:
        stats = {
            'total_entries': len(self.entries),
            'severity_counts': {},
            'event_type_counts': {},
            'status_counts': {},
            'time_range': {
                'start': self.entries[0].timestamp if self.entries else None,
                'end': self.entries[-1].timestamp if self.entries else None
            }
        }
        
        for entry in self.entries:
            stats['severity_counts'][entry.severity] = stats['severity_counts'].get(entry.severity, 0) + 1
            stats['event_type_counts'][entry.event_type] = stats['event_type_counts'].get(entry.event_type, 0) + 1
            stats['status_counts'][entry.status] = stats['status_counts'].get(entry.status, 0) + 1
        
        return stats
    
    def generate_audit_report(self) -> Dict:
        return {
            'generated_at': datetime.datetime.now().isoformat(),
            'session_id': str(uuid.uuid4())[:8],
            'statistics': self.get_statistics(),
            'recent_entries': [e.to_dict() for e in self.entries[-50:]],
            'system_info': {
                'logger_name': self.name,
                'log_directory': str(self.log_dir)
            }
        }
    
    # Shortcut methods for logging
    def debug(self, message: str, **kwargs):
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self.logger.critical(message, **kwargs)


# ============================================================
# GLOBAL LOGGER INSTANCE
# ============================================================

_default_logger = None

def get_logger(name: str = "ThreeWayMatching", log_dir: str = "./logs") -> AuditLogger:
    global _default_logger
    if _default_logger is None or _default_logger.name != name:
        _default_logger = AuditLogger(log_dir=log_dir, name=name)
    return _default_logger


def setup_logging(log_dir: str = "./logs", name: str = "ThreeWayMatching") -> AuditLogger:
    return get_logger(name=name, log_dir=log_dir)