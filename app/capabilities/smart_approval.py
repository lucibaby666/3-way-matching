"""
Smart Approval System with ChromaDB Exception Precedents & Auto-Approval
Provides vector similarity matching for 3-way matching exceptions.
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from database_operations import (
        create_audit_tables,
        insert_audit_to_db,
    )
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    try:
        from database_operations import (
            create_audit_tables,
            insert_audit_to_db,
        )
    except ImportError:
        def create_audit_tables():
            return False
        def insert_audit_to_db(entry):
            return False

logger = logging.getLogger("ThreeWayMatching")

# Check ChromaDB availability
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB not installed. Auto-approval will default to manual review.")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False


class ChromaVectorDatabase:
    """
    ChromaDB Vector Database for storing and retrieving historical exception precedents.
    """

    def __init__(self, persist_path: str = "./chroma_db_store"):
        self.persist_path = persist_path
        self.collection_name = "exception_precedents"

        # Ensure database tables exist
        try:
            create_audit_tables()
        except Exception as e:
            logger.warning(f"Audit table creation warning: {e}")

        if CHROMADB_AVAILABLE:
            try:
                os.makedirs(persist_path, exist_ok=True)
                self.client = chromadb.PersistentClient(
                    path=persist_path,
                    settings=Settings(anonymized_telemetry=False),
                )
                self.collection = self.client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"✅ ChromaDB ready: {self.collection.count()} precedent vectors")
            except Exception as e:
                logger.warning(f"⚠️ ChromaDB init failed: {e}")
                self.client = None
                self.collection = None
        else:
            self.client = None
            self.collection = None

    def generate_signature(self, exception: dict) -> str:
        """Create a normalized textual signature for vectorization"""
        exc_type = exception.get("type", "UNKNOWN") or "UNKNOWN"
        item_code = exception.get("item_code", "UNKNOWN") or "UNKNOWN"
        field = exception.get("field", "UNKNOWN") or "UNKNOWN"
        expected = exception.get("expected", "N/A")
        actual = exception.get("actual", "N/A")
        tolerance = exception.get("tolerance", "NONE") or "NONE"

        return f"""
        TYPE: {exc_type}
        ITEM: {item_code}
        FIELD: {field}
        EXPECTED: {expected}
        ACTUAL: {actual}
        TOLERANCE: {tolerance}
        """.strip()

    def store_precedent(
        self,
        exception: dict,
        decision: str,
        reviewer: str,
        comment: str = "",
    ) -> Optional[str]:
        """Store a human decision into ChromaDB as a precedent"""
        if not self.collection:
            logger.warning("ChromaDB collection not available to store precedent")
            return None

        try:
            signature = self.generate_signature(exception)
            unique_hash = hashlib.md5(signature.encode()).hexdigest()[:8]
            precedent_id = f"PREC-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{unique_hash}"

            metadata = {
                "decision": str(decision.upper()),
                "reviewer": str(reviewer or "system"),
                "comment": str(comment or ""),
                "exception_type": str(exception.get("type", "UNKNOWN") or "UNKNOWN"),
                "item_code": str(exception.get("item_code", "UNKNOWN") or "UNKNOWN"),
                "field": str(exception.get("field", "UNKNOWN") or "UNKNOWN"),
                "expected": str(exception.get("expected", "N/A") or "N/A"),
                "actual": str(exception.get("actual", "N/A") or "N/A"),
                "created_at": datetime.now().isoformat(),
            }

            metadata = {k: (v if v is not None else "") for k, v in metadata.items()}

            self.collection.add(
                ids=[precedent_id],
                documents=[signature],
                metadatas=[metadata],
            )

            # Insert audit record to database
            audit_entry = {
                "audit_id": f"PREC-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "event_type": "PRECEDENT_STORED",
                "severity": "INFO",
                "user": reviewer or "system",
                "action": f"Precedent stored: {precedent_id}",
                "resource": precedent_id,
                "resource_type": "PRECEDENT",
                "status": "SUCCESS",
                "error": None,
                "metadata": {
                    "precedent_id": precedent_id,
                    "exception_type": exception.get("type", "UNKNOWN"),
                    "item_code": exception.get("item_code", "UNKNOWN"),
                    "decision": decision,
                    "comment": comment,
                },
            }
            insert_audit_to_db(audit_entry)

            logger.info(f"✅ Precedent stored: {precedent_id}")
            return precedent_id

        except Exception as e:
            logger.error(f"Failed to store precedent in ChromaDB: {e}")
            return None

    def find_similar(
        self,
        exception: dict,
        threshold: float = 0.95,
    ) -> Optional[dict]:
        """Search ChromaDB for historical precedents matching the exception"""
        if not self.collection:
            return None

        try:
            signature = self.generate_signature(exception)

            results = self.collection.query(
                query_texts=[signature],
                n_results=5,
                include=["documents", "metadatas", "distances"],
            )

            if not results["ids"] or not results["ids"][0]:
                return None

            best_distance = (
                results["distances"][0][0] if results["distances"][0] else 1.0
            )
            # Cosine similarity in chromadb with hnsw:space=cosine is 1 - distance
            best_similarity = 1 - best_distance

            if best_similarity >= threshold:
                best_metadata = (
                    results["metadatas"][0][0] if results["metadatas"][0] else {}
                )

                return {
                    "precedent_id": results["ids"][0][0],
                    "decision": best_metadata.get("decision", "APPROVED"),
                    "similarity": round(best_similarity, 4),
                    "reviewer": best_metadata.get("reviewer", "system"),
                    "comment": best_metadata.get("comment", ""),
                    "exception_type": best_metadata.get("exception_type", ""),
                    "item_code": best_metadata.get("item_code", ""),
                }

            return None

        except Exception as e:
            logger.warning(f"ChromaDB search failed: {e}")
            return None

    def get_stats(self) -> dict:
        if self.collection:
            try:
                return {"total_vectors": self.collection.count()}
            except Exception:
                pass
        return {"total_vectors": 0}


class SmartApprovalSystem:
    """
    Intelligent Approval System coordinating ChromaDB precedent retrieval and auto-approvals.
    """

    def __init__(self, threshold: float = 0.95):
        self.threshold = threshold
        self.vector_db = ChromaVectorDatabase()
        self.auto_approved = 0
        self.human_reviewed = 0
        self.total_processed = 0

    def process_exception(self, exception: dict) -> dict:
        """
        Evaluate an exception against historical precedents.
        Returns auto-approval decision if similarity >= threshold, otherwise routes to HITL.
        """
        self.total_processed += 1

        exc_type = exception.get("type", "UNKNOWN") or "UNKNOWN"
        item_code = exception.get("item_code", "UNKNOWN") or "UNKNOWN"

        logger.info(f"Evaluating exception for Smart Approval: {exc_type} on {item_code}")

        precedent = self.vector_db.find_similar(exception, self.threshold)

        if precedent:
            self.auto_approved += 1

            result = {
                "decision": precedent["decision"],
                "auto_approved": True,
                "precedent_id": precedent["precedent_id"],
                "similarity_score": precedent["similarity"],
                "reviewer": precedent["reviewer"],
                "comment": precedent["comment"],
            }

            reviewer_name = precedent.get("reviewer") or "smart-approval-ai"
            audit_entry = {
                "audit_id": f"AUTO-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "event_type": "AUTO_APPROVAL",
                "severity": "INFO",
                "user": reviewer_name,
                "action": f"Auto-{precedent['decision']}: {exc_type} on {item_code} (Precedent by {reviewer_name})",
                "resource": f"precedent:{precedent['precedent_id']}",
                "resource_type": "EXCEPTION",
                "status": precedent["decision"],
                "error": None,
                "metadata": {
                    "approved_by": reviewer_name,
                    "exception_type": exc_type,
                    "item_code": item_code,
                    "expected": str(exception.get("expected")),
                    "actual": str(exception.get("actual")),
                    "field": str(exception.get("field")),
                    "precedent_id": precedent["precedent_id"],
                    "similarity_score": precedent["similarity"],
                    "reviewer": reviewer_name,
                    "comment": precedent.get("comment"),
                },
            }
            insert_audit_to_db(audit_entry)

            logger.info(f"✅ AUTO-{precedent['decision']} (Score: {precedent['similarity']:.4f})")

            return result
        else:
            self.human_reviewed += 1

            audit_entry = {
                "audit_id": f"HITL-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "event_type": "HUMAN_REVIEW_REQUIRED",
                "severity": "WARNING",
                "user": "system",
                "action": f"Human review required: {exc_type} on {item_code}",
                "resource": f"exception:{item_code}",
                "resource_type": "EXCEPTION",
                "status": "PENDING",
                "error": "No similar precedent found",
                "metadata": {
                    "exception_type": exc_type,
                    "item_code": item_code,
                    "expected": str(exception.get("expected")),
                    "actual": str(exception.get("actual")),
                    "field": str(exception.get("field")),
                },
            }
            insert_audit_to_db(audit_entry)
            logger.info(f"❌ No matching precedent - Routing to Human Review")

            return {
                "decision": "PENDING",
                "auto_approved": False,
                "precedent_id": None,
                "similarity_score": None,
                "reviewer": None,
                "comment": None,
            }

    def store_human_decision(
        self,
        exception: dict,
        decision: str,
        reviewer: str,
        comment: str = "",
    ) -> bool:
        """Record a human decision as a new precedent into ChromaDB and DB audit log"""
        exc_type = exception.get("type", "UNKNOWN") or "UNKNOWN"
        item_code = exception.get("item_code", "UNKNOWN") or "UNKNOWN"

        audit_entry = {
            "audit_id": f"HITL-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "event_type": "HUMAN_DECISION",
            "severity": "INFO",
            "user": reviewer or "system",
            "action": f"Human {decision}: {exc_type} on {item_code}",
            "resource": f"exception:{item_code}",
            "resource_type": "EXCEPTION",
            "status": decision.upper(),
            "error": None,
            "metadata": {
                "exception_type": exc_type,
                "item_code": item_code,
                "expected": str(exception.get("expected")),
                "actual": str(exception.get("actual")),
                "field": str(exception.get("field")),
                "decision": decision,
                "reviewer": reviewer,
                "comment": comment,
            },
        }
        insert_audit_to_db(audit_entry)

        precedent_id = self.vector_db.store_precedent(
            exception=exception,
            decision=decision,
            reviewer=reviewer,
            comment=comment,
        )

        return precedent_id is not None

    def get_stats(self) -> dict:
        db_stats = self.vector_db.get_stats()
        return {
            "total_processed": self.total_processed,
            "auto_approved": self.auto_approved,
            "human_reviewed": self.human_reviewed,
            "threshold": self.threshold,
            "chromadb_vectors": db_stats.get("total_vectors", 0),
            "chromadb_available": CHROMADB_AVAILABLE,
        }


# Global singleton instance
_smart_approval_instance: Optional[SmartApprovalSystem] = None


def get_smart_approval_system(threshold: float = 0.95) -> SmartApprovalSystem:
    global _smart_approval_instance
    if _smart_approval_instance is None:
        _smart_approval_instance = SmartApprovalSystem(threshold=threshold)
    return _smart_approval_instance
