"""
COMPLETE SMART APPROVAL SYSTEM WITH CHROMADB
Includes: 3-Way Matching, Auto-Approval, Human Review, Logging
Fixed: Approval option always appears when exceptions exist
"""

import asyncio
import json
import hashlib
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# IMPORTS FROM SEPARATED MODULES
# ============================================================

from logging_operations import logger, log_and_insert, AuditSeverity
from database_operations import (
    get_db_connection,
    create_audit_tables,
    insert_audit_to_db,
    insert_statistics_to_db,
    DB_CONFIG
)

# ============================================================
# IMPORTS
# ============================================================

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
    print("✅ ChromaDB loaded successfully")
except ImportError:
    CHROMADB_AVAILABLE = False
    print("⚠️ ChromaDB not installed. Run: pip install chromadb")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False
    print("⚠️ sentence-transformers not installed. Run: pip install sentence-transformers")

# Import your existing app modules
try:
    from app.agents.matching_agent import create_matching_agent
    from app.capabilities.contract_extractor import ContractExtractor
    from app.capabilities.document_intake import DocumentIntake
    from app.capabilities.evidence_generator import EvidenceGenerator
    from app.capabilities.hitl_case_service import HITLCaseService
    from app.capabilities.hitl_decision import HITLDecisionCapability
    from app.capabilities.hitl_routing import HITLRoutingCapability
    from app.capabilities.invoice_extractor import InvoiceExtractor
    from app.capabilities.purchase_order_extractor import PurchaseOrderExtractor
    from app.capabilities.smart_approval import (
        ChromaVectorDatabase,
        SmartApprovalSystem,
        get_smart_approval_system,
    )
    from app.canonicalization.canonicalizer import Canonicalizer
    from app.matching.matching_engine import MatchingEngine
    from app.models.hitl_decision import HITLDecision, HITLDecisionType
    from app.repositories.in_memory_hitl_case_repository import InMemoryHITLCaseRepository
    APP_MODULES_AVAILABLE = True
    print("✅ App modules loaded successfully")
except ImportError as e:
    APP_MODULES_AVAILABLE = False
    print(f"⚠️ Import error: {e}")
    logger.error(f"Import error: {e}")


# ============================================================
# SAFE GETTER FUNCTION
# ============================================================


def safe_get(data, key, default=None):
    if data is None:
        return default
    return data.get(key, default)


# ============================================================
# LOG GENERATION HELPERS (Using separated functions)
# ============================================================

def log_matching_status(status, exception_count):
    audit_entry = {
        "audit_id": f"MATCH-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": "MATCHING_COMPLETE",
        "severity": "INFO",
        "user": "system",
        "action": f"Matching completed with status: {status}",
        "resource": "matching",
        "resource_type": "SYSTEM",
        "status": status,
        "error": None,
        "metadata": {
            "matching_status": status,
            "exception_count": exception_count,
            "timestamp": datetime.now().isoformat()
        }
    }
    insert_audit_to_db(audit_entry)


def log_no_exceptions():
    audit_entry = {
        "audit_id": f"NOEXC-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": "NO_EXCEPTIONS_FOUND",
        "severity": "INFO",
        "user": "system",
        "action": "No exceptions found - All documents match",
        "resource": "matching",
        "resource_type": "SYSTEM",
        "status": "SUCCESS",
        "error": None,
        "metadata": {
            "message": "All documents matched successfully",
            "timestamp": datetime.now().isoformat()
        }
    }
    insert_audit_to_db(audit_entry)


def log_demo_summary(smart_approval):
    stats = smart_approval.get_stats()
    audit_entry = {
        "audit_id": f"DEMO-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": "DEMO_SUMMARY",
        "severity": "INFO",
        "user": "system",
        "action": "Smart Approval Demo Summary",
        "resource": "demo",
        "resource_type": "SYSTEM",
        "status": "SUCCESS",
        "error": None,
        "metadata": {
            "total_processed": stats['total_processed'],
            "auto_approved": stats['auto_approved'],
            "human_reviewed": stats['human_reviewed'],
            "chromadb_vectors": stats['chromadb_vectors'],
            "similarity_threshold": stats['threshold']
        }
    }
    insert_audit_to_db(audit_entry)


# ============================================================
# INJECT DISCREPANCY FOR DEMO
# ============================================================

def inject_discrepancy(invoice):
    if not invoice or not hasattr(invoice, 'line_items') or not invoice.line_items:
        return
    
    print("\n📝 Injecting controlled discrepancy for demo...")
    logger.info("Injecting controlled discrepancy for demo...")
    
    original_qty = invoice.line_items[0].quantity
    original_price = invoice.line_items[0].unit_price
    
    invoice.line_items[0].quantity = original_qty * 1.1
    invoice.line_items[0].unit_price = original_price * 1.04
    
    print(f"   ITM-001: Quantity {original_qty} → {invoice.line_items[0].quantity}")
    print(f"   ITM-001: Price {original_price} → {invoice.line_items[0].unit_price}")
    logger.info(f"   ITM-001: Quantity {original_qty} → {invoice.line_items[0].quantity}")
    logger.info(f"   ITM-001: Price {original_price} → {invoice.line_items[0].unit_price}")
    
    audit_entry = {
        "audit_id": f"INJ-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": "DISCREPANCY_INJECTED",
        "severity": "WARNING",
        "user": "demo",
        "action": "Controlled discrepancy injected for demo",
        "resource": "ITM-001",
        "resource_type": "INVOICE",
        "status": "MODIFIED",
        "error": None,
        "metadata": {
            "item": "ITM-001",
            "original_quantity": float(original_qty),
            "new_quantity": float(invoice.line_items[0].quantity),
            "original_price": float(original_price),
            "new_price": float(invoice.line_items[0].unit_price),
            "timestamp": datetime.now().isoformat()
        }
    }
    insert_audit_to_db(audit_entry)


# ============================================================
# HUMAN REVIEW FUNCTION (FIXED - Always Shows When Exceptions Exist)
# ============================================================

def run_human_review(exceptions, smart_approval, logger):
    """
    Run human review for exceptions.
    This function ALWAYS shows the approval option when exceptions exist.
    """
    print("\n" + "=" * 60)
    print("👤 HUMAN REVIEW REQUIRED")
    print("=" * 60)
    
    # Show all exceptions
    print("\n📋 Exception Details:")
    print("-" * 40)
    
    for i, exception in enumerate(exceptions):
        print(f"\nException {i+1}:")
        if hasattr(exception, 'type'):
            print(f"  Type: {exception.type}")
        if hasattr(exception, 'item_code'):
            print(f"  Item: {exception.item_code}")
        if hasattr(exception, 'field'):
            print(f"  Field: {exception.field}")
        if hasattr(exception, 'expected'):
            print(f"  Expected: {exception.expected}")
        if hasattr(exception, 'actual'):
            print(f"  Actual: {exception.actual}")
        if hasattr(exception, 'tolerance') and exception.tolerance:
            print(f"  Tolerance: {exception.tolerance}")
        if hasattr(exception, 'evidence') and exception.evidence:
            print("  Evidence:")
            for evidence in exception.evidence:
                print(f"    - {evidence.get('snip_path', 'N/A')}")
    
    print("\n" + "-" * 60)
    print("Please review the exceptions above.")
    print("Type APPROVE ALL to approve all exceptions.")
    print("Type REJECT ALL to reject all exceptions.")
    print("Type SKIP to skip.")
    print("-" * 60)
    
    while True:
        user_input = input("\nReviewer decision: ").strip().upper()
        
        if user_input == "APPROVE ALL":
            print("\n✅ ALL EXCEPTIONS APPROVED!")
            logger.info("✅ ALL EXCEPTIONS APPROVED!")
            
            for exception in exceptions:
                exception_dict = {
                    "type": str(exception.type) if hasattr(exception, 'type') else 'UNKNOWN',
                    "item_code": exception.item_code if hasattr(exception, 'item_code') else 'UNKNOWN',
                    "field": str(exception.field) if hasattr(exception, 'field') else 'UNKNOWN',
                    "expected": exception.expected if hasattr(exception, 'expected') else 'N/A',
                    "actual": exception.actual if hasattr(exception, 'actual') else 'N/A',
                    tolerance=getattr(exception, "tolerance", None),
                    evidence=exception.evidence if hasattr(exception, 'evidence') else []
                )
                smart_approval.store_human_decision(
                    exception_dict,
                    decision="APPROVED",
                    reviewer=os.getenv("DB_USERNAME", "umarwani"),
                    comment="Approved by reviewer"
                )
            return "APPROVED"
            
        elif user_input == "REJECT ALL":
            print("\n❌ ALL EXCEPTIONS REJECTED!")
            logger.info("❌ ALL EXCEPTIONS REJECTED!")
            
            for exception in exceptions:
                exception_dict = dict(
                    type=str(exception.type) if hasattr(exception, 'type') else 'UNKNOWN',
                    item_code=exception.item_code if hasattr(exception, 'item_code') else 'UNKNOWN',
                    field=str(exception.field) if hasattr(exception, 'field') else 'UNKNOWN',
                    expected=exception.expected if hasattr(exception, 'expected') else 'N/A',
                    actual=exception.actual if hasattr(exception, 'actual') else 'N/A',
                    tolerance=getattr(exception, "tolerance", None),
                    evidence=exception.evidence if hasattr(exception, 'evidence') else []
                )
                smart_approval.store_human_decision(
                    exception_dict,
                    decision="REJECTED",
                    reviewer=os.getenv("DB_USERNAME", "umarwani"),
                    comment="Rejected by reviewer"
                )
            return "REJECTED"

            
        elif user_input == "SKIP":
            print("\n⏭️ Skipping review")
            logger.info("⏭️ Skipping review")
            return "SKIPPED"
            
        else:
            print("Invalid input. Please type APPROVE ALL, REJECT ALL, or SKIP.")


# ============================================================
# MAIN APPLICATION
# ============================================================

async def main():
    print("\n" + "=" * 70)
    print("🚀 3-WAY MATCHING WITH SMART APPROVAL & CHROMADB")
    print("📝 FULL LOG GENERATION ENABLED (DB + LOCAL FILES)")
    print("=" * 70)
    
    logger.info("=" * 70)
    logger.info("🚀 3-WAY MATCHING WITH SMART APPROVAL & CHROMADB")
    logger.info("=" * 70)
    
    # Check if app modules are available
    if not APP_MODULES_AVAILABLE:
        print("\n❌ App modules not available. Please ensure:")
        print("   1. You're running from the correct directory")
        print("   2. All app modules are installed")
        print("   3. The app folder is in your PYTHONPATH")
        return
    
    # Initialize and verify Database
    print("\n🔍 Checking Database Connection...")
    conn = get_db_connection()
    if conn:
        print("   ✅ Connected to Database successfully")
        logger.info("Connected to Database successfully")
        create_audit_tables()
        conn.close()
    else:
        print("   ⚠️ Database not connected. Audit logs will only be written to local files.")
        print("   💡 Tip: Check your Azure SQL credentials in .env")
        logger.warning("Database not connected. Audit logs will only be written to local files.")

    # Initialize Smart Approval
    smart_approval = SmartApprovalSystem(threshold=0.95)
    
    # Demo mode
    inject_for_demo = True
    
    # Log system start using separated function
    audit_entry = {
        "audit_id": f"SYS-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": "SYSTEM_START",
        "severity": "INFO",
        "user": "system",
        "action": "Starting 3-Way Matching with Smart Approval",
        "resource": "system",
        "resource_type": "SYSTEM",
        "status": "SUCCESS",
        "error": None,
        "metadata": {
            "smart_approval_enabled": True,
            "similarity_threshold": smart_approval.threshold,
            "demo_mode": inject_for_demo,
            "timestamp": datetime.now().isoformat()
        }
    }
    insert_audit_to_db(audit_entry)
    
    try:
        # ========================================================
        # DOCUMENT INTAKE
        # ========================================================
        
        print("\n[1] DOCUMENT INTAKE")
        logger.info("-" * 70)
        logger.info("[1] DOCUMENT INTAKE")
        
        try:
            intake = DocumentIntake()
            documents = intake.discover_documents()
        except Exception as e:
            error_msg = f"Document intake failed: {e}"
            logger.error(error_msg)
            print(f"❌ {error_msg}")
            raise

        contracts = documents.get("contracts", [])
        pos = documents.get("purchase_orders", [])
        invoices = documents.get("invoices", [])
        
        if not contracts:
            error_msg = "No contract found!"
            logger.error(error_msg)
            print(f"❌ {error_msg}")
            audit_entry = {
                "audit_id": f"ERR-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "event_type": "DOCUMENT_ERROR",
                "severity": "CRITICAL",
                "user": "system",
                "action": error_msg,
                "resource": "document",
                "resource_type": "DOCUMENT",
                "status": "FAILED",
                "error": error_msg,
                "metadata": {}
            }
            insert_audit_to_db(audit_entry)
            return
        
        contract_doc = contracts[0] if contracts else None
        po_doc = pos[0] if pos else None
        invoice_doc = invoices[0] if invoices else None
        
        print(f"   Contract: {contract_doc.get('filename', 'N/A') if contract_doc else 'N/A'}")
        print(f"   PO: {po_doc.get('filename', 'N/A') if po_doc else 'Not found'}")
        print(f"   Invoice: {invoice_doc.get('filename', 'N/A') if invoice_doc else 'Not found'}")
        
        logger.info(f"   Contract: {contract_doc.get('filename', 'N/A') if contract_doc else 'N/A'}")
        logger.info(f"   PO: {po_doc.get('filename', 'N/A') if po_doc else 'Not found'}")
        logger.info(f"   Invoice: {invoice_doc.get('filename', 'N/A') if invoice_doc else 'Not found'}")
        
        audit_entry = {
            "audit_id": f"DOC-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "event_type": "DOCUMENT_INTAKE_COMPLETE",
            "severity": "INFO",
            "user": "system",
            "action": "Document intake completed",
            "resource": contract_doc.get('filename', '') if contract_doc else '',
            "resource_type": "DOCUMENT",
            "status": "SUCCESS",
            "error": None,
            "metadata": {
                "contract": contract_doc.get('filename') if contract_doc else None,
                "po": po_doc.get('filename') if po_doc else None,
                "invoice": invoice_doc.get('filename') if invoice_doc else None,
                "timestamp": datetime.now().isoformat()
            }
        }
        insert_audit_to_db(audit_entry)
        
        # ========================================================
        # EXTRACTION
        # ========================================================
        
        print("\n[2] DOCUMENT EXTRACTION")
        logger.info("[2] DOCUMENT EXTRACTION")
        
        try:
            contract_extractor = ContractExtractor()
            po_extractor = PurchaseOrderExtractor()
            invoice_extractor = InvoiceExtractor()
            
            contract_data = contract_extractor.extract_contract(contract_doc["path"]) if contract_doc else {}
            
            if contract_data is None:
                print("   ⚠️ Contract extraction returned None - using empty data")
                logger.warning("Contract extraction returned None - using empty data")
                contract_data = {}
            
            po_data = po_extractor.extract_purchase_order(po_doc["path"]) if po_doc else {}
            invoice_data = invoice_extractor.extract_invoice(invoice_doc["path"]) if invoice_doc else {}
        except Exception as e:
            error_msg = f"Extraction failed: {e}"
            logger.error(error_msg)
            print(f"❌ {error_msg}")
            raise
        
        contract_number = safe_get(contract_data, 'contract_number', {})
        contract_number_val = safe_get(contract_number, 'value', 'N/A')
        
        po_number = safe_get(po_data, 'po_number', {})
        po_number_val = safe_get(po_number, 'value', 'N/A')
        
        invoice_number = safe_get(invoice_data, 'invoice_number', {})
        invoice_number_val = safe_get(invoice_number, 'value', 'N/A')
        
        print(f"   Contract: {contract_number_val}")
        print(f"   PO: {po_number_val}")
        print(f"   Invoice: {invoice_number_val}")
        logger.info(f"   Contract: {contract_number_val}")
        logger.info(f"   PO: {po_number_val}")
        logger.info(f"   Invoice: {invoice_number_val}")
        
        # ========================================================
        # CANONICALIZATION
        # ========================================================
        
        print("\n[3] CANONICALIZATION")
        logger.info("[3] CANONICALIZATION")
        
        canonicalizer = Canonicalizer()
        
        try:
            contract = canonicalizer.canonicalize_contract(
                contract_data, 
                document_id=contract_doc.get("document_id", "contract_001") if contract_doc else "contract_001"
            )
            purchase_order = canonicalizer.canonicalize_purchase_order(
                po_data, 
                document_id=po_doc.get("document_id", "po_001") if po_doc else "po_001"
            )
            invoice = canonicalizer.canonicalize_invoice(
                invoice_data, 
                document_id=invoice_doc.get("document_id", "invoice_001") if invoice_doc else "invoice_001"
            )
        except TypeError as e:
            print(f"   ⚠️ Canonicalization error: {e}")
            logger.warning(f"Canonicalization error: {e}")
            print("   Trying without document_id...")
            
            try:
                contract = canonicalizer.canonicalize_contract(contract_data)
                purchase_order = canonicalizer.canonicalize_purchase_order(po_data) if po_data else None
                invoice = canonicalizer.canonicalize_invoice(invoice_data) if invoice_data else None
            except Exception as e2:
                print(f"   ❌ Still failing: {e2}")
                logger.error(f"Canonicalization failed: {e2}")
                raise
        
        contract_lines = len(contract.line_items) if hasattr(contract, 'line_items') else 0
        po_lines = len(purchase_order.line_items) if hasattr(purchase_order, 'line_items') else 0
        invoice_lines = len(invoice.line_items) if hasattr(invoice, 'line_items') else 0
        
        print(f"   Contract lines: {contract_lines}")
        print(f"   PO lines: {po_lines}")
        print(f"   Invoice lines: {invoice_lines}")
        logger.info(f"   Contract lines: {contract_lines}")
        logger.info(f"   PO lines: {po_lines}")
        logger.info(f"   Invoice lines: {invoice_lines}")
        
        # ========================================================
        # INJECT DISCREPANCY FOR DEMO
        # ========================================================
        
        if inject_for_demo and invoice and hasattr(invoice, 'line_items') and invoice.line_items:
            inject_discrepancy(invoice)
        
        # ========================================================
        # MATCHING
        # ========================================================
        
        print("\n[4] DETERMINISTIC MATCHING")
        logger.info("[4] DETERMINISTIC MATCHING")
        
        try:
            engine = MatchingEngine()
            deterministic_result = engine.match(contract, purchase_order, invoice)
            
            print(f"   Status: {deterministic_result.status}")
            logger.info(f"   Status: {deterministic_result.status}")
            
            exception_count = len(deterministic_result.exceptions) if deterministic_result.exceptions else 0
            print(f"   Exceptions: {exception_count}")
            logger.info(f"   Exceptions: {exception_count}")
            
            log_matching_status(deterministic_result.status, exception_count)
            
        except Exception as e:
            error_msg = f"Matching failed: {e}"
            logger.error(error_msg)
            print(f"❌ {error_msg}")
            raise
        
        # ========================================================
        # SMART APPROVAL PROCESSING
        # ========================================================
        
        print("\n[5] SMART APPROVAL PROCESSING")
        print("-" * 50)
        logger.info("[5] SMART APPROVAL PROCESSING")
        logger.info("-" * 50)
        
        auto_approved_list = []
        human_review_list = []
        
        if not deterministic_result.exceptions:
            print("   ✅ No exceptions found")
            logger.info("   ✅ No exceptions found")
            log_no_exceptions()
            
            audit_entry = {
                "audit_id": f"SYS-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "event_type": "SYSTEM_COMPLETE",
                "severity": "INFO",
                "user": "system",
                "action": "3-Way Matching with Smart Approval completed - No exceptions",
                "resource": "system",
                "resource_type": "SYSTEM",
                "status": "SUCCESS",
                "error": None,
                "metadata": {
                    "matching_status": deterministic_result.status,
                    "exception_count": 0,
                    "auto_approved": 0,
                    "human_reviewed": 0,
                    "chromadb_vectors": smart_approval.get_stats()['chromadb_vectors'],
                    "timestamp": datetime.now().isoformat()
                }
            }
            insert_audit_to_db(audit_entry)
            
        else:
            # Process exceptions with smart approval
            for exception in deterministic_result.exceptions:
                exception_dict = {
                    "type": str(exception.type) if hasattr(exception, 'type') else 'UNKNOWN',
                    "item_code": exception.item_code if hasattr(exception, 'item_code') else 'UNKNOWN',
                    "field": str(exception.field) if hasattr(exception, 'field') else 'UNKNOWN',
                    "expected": exception.expected if hasattr(exception, 'expected') else 'N/A',
                    "actual": exception.actual if hasattr(exception, 'actual') else 'N/A',
                    "tolerance": getattr(exception, "tolerance", None),
                    "evidence": exception.evidence if hasattr(exception, 'evidence') else []
                }
                
                # Clean None values
                for key, value in exception_dict.items():
                    if value is None:
                        if key == 'type':
                            exception_dict[key] = 'UNKNOWN'
                        elif key == 'item_code':
                            exception_dict[key] = 'UNKNOWN'
                        elif key == 'field':
                            exception_dict[key] = 'UNKNOWN'
                        elif key == 'expected':
                            exception_dict[key] = 'N/A'
                        elif key == 'actual':
                            exception_dict[key] = 'N/A'
                
                result = smart_approval.process_exception(exception_dict)
                
                if result['auto_approved']:
                    auto_approved_list.append(result)
                    print(f"   🤖 Auto-{result['decision']}: {exception_dict['type']} on {exception_dict['item_code']}")
                    logger.info(f"   🤖 Auto-{result['decision']}: {exception_dict['type']} on {exception_dict['item_code']}")
                else:
                    human_review_list.append((exception, exception_dict))
                    print(f"   👤 Human Review Required: {exception_dict['type']} on {exception_dict['item_code']}")
                    logger.info(f"   👤 Human Review Required: {exception_dict['type']} on {exception_dict['item_code']}")
            
            # ⭐ FIX: ALWAYS show human review if there are exceptions that need review
            if human_review_list:
                print("\n" + "-" * 50)
                print("👤 HUMAN REVIEW REQUIRED FOR UNRESOLVED EXCEPTIONS")
                print("-" * 50)
                
                # Run human review for all unresolved exceptions
                review_result = run_human_review(
                    [item[0] for item in human_review_list],
                    smart_approval,
                    logger
                )
                
                print(f"\n📋 Human Review Result: {review_result}")
                logger.info(f"Human Review Result: {review_result}")
            
            # Final statistics
            stats = smart_approval.get_stats()
            audit_entry = {
                "audit_id": f"SYS-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "event_type": "SYSTEM_COMPLETE",
                "severity": "INFO",
                "user": "system",
                "action": "3-Way Matching with Smart Approval completed - Exceptions processed",
                "resource": "system",
                "resource_type": "SYSTEM",
                "status": "SUCCESS",
                "error": None,
                "metadata": {
                    "matching_status": deterministic_result.status,
                    "exception_count": len(deterministic_result.exceptions),
                    "auto_approved": stats['auto_approved'],
                    "human_reviewed": stats['human_reviewed'],
                    "chromadb_vectors": stats['chromadb_vectors'],
                    "timestamp": datetime.now().isoformat()
                }
            }
            insert_audit_to_db(audit_entry)
        
        # ========================================================
        # FINAL SUMMARY
        # ========================================================
        
        print("\n" + "=" * 70)
        print("📊 FINAL SUMMARY")
        print("=" * 70)
        logger.info("=" * 70)
        logger.info("📊 FINAL SUMMARY")
        logger.info("=" * 70)
        
        stats = smart_approval.get_stats()
        print(f"\n📈 Smart Approval Statistics:")
        print(f"   Total Exceptions: {stats['total_processed']}")
        print(f"   Auto-Approved: {stats['auto_approved']}")
        print(f"   Human Reviewed: {stats['human_reviewed']}")
        print(f"   ChromaDB Vectors: {stats['chromadb_vectors']}")
        print(f"   Similarity Threshold: {stats['threshold']}")
        
        logger.info(f"   Total Exceptions: {stats['total_processed']}")
        logger.info(f"   Auto-Approved: {stats['auto_approved']}")
        logger.info(f"   Human Reviewed: {stats['human_reviewed']}")
        logger.info(f"   ChromaDB Vectors: {stats['chromadb_vectors']}")
        logger.info(f"   Similarity Threshold: {stats['threshold']}")
        
        print(f"\n📝 Logs Generated in Database:")
        print(f"   ✅ SYSTEM_START")
        print(f"   ✅ DOCUMENT_INTAKE_COMPLETE")
        
        if deterministic_result.exceptions:
            print(f"   ✅ AUTO_APPROVAL")
            print(f"   ✅ HUMAN_REVIEW_REQUIRED")
            print(f"   ✅ HUMAN_DECISION")
            print(f"   ✅ PRECEDENT_STORED")
        else:
            print(f"   ✅ NO_EXCEPTIONS_FOUND")
        
        print(f"   ✅ MATCHING_COMPLETE")
        print(f"   ✅ SYSTEM_COMPLETE")
        print(f"   ✅ DEMO_SUMMARY")
        
        log_demo_summary(smart_approval)
        
        print("\n" + "=" * 70)
        print("✅ COMPLETE - Check audit_logs table for all logs")
        print("=" * 70)
        logger.info("=" * 70)
        logger.info("✅ COMPLETE - Check audit_logs table for all logs")
        logger.info("=" * 70)
        
        # Verify database entries
        print("\n📊 Verifying database entries...")
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM audit_logs")
                count = cursor.fetchone()[0]
                print(f"   ✅ Total logs in database: {count}")
                logger.info(f"   ✅ Total logs in database: {count}")
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"   ⚠️ Could not verify: {e}")
                logger.warning(f"Could not verify: {e}")
        
        # Local log file location
        log_file = Path("./logs") / f"ThreeWayMatching_{datetime.now().strftime('%Y%m%d')}.log"
        print(f"\n📁 Local log file: {log_file}")
        logger.info(f"📁 Local log file: {log_file}")
        
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error occurred"
        print(f"\n❌ Error: {error_msg}")
        logger.error(f"Demo failed: {error_msg}")
        
        audit_entry = {
            "audit_id": f"ERR-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "event_type": "SYSTEM_ERROR",
            "severity": "CRITICAL",
            "user": "system",
            "action": f"System error: {error_msg}",
            "resource": "system",
            "resource_type": "SYSTEM",
            "status": "FAILED",
            "error": error_msg,
            "metadata": {
                "error": error_msg,
                "traceback": str(e)
            }
        }
        insert_audit_to_db(audit_entry)
        raise


if __name__ == "__main__":
    asyncio.run(main())