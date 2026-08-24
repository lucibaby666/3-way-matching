import asyncio
import json
from datetime import datetime, timezone

from app.agents.matching_agent import create_matching_agent
from app.capabilities.document_set_loader import (
    DocumentSetLoader,
)
from app.capabilities.evidence_generator import EvidenceGenerator
from app.capabilities.hitl_case_service import HITLCaseService
from app.capabilities.hitl_decision import HITLDecisionCapability
from app.capabilities.hitl_routing import HITLRoutingCapability
from app.matching.matching_engine import MatchingEngine
from app.models.hitl_decision import (
    HITLDecision,
    HITLDecisionType,
)
from app.repositories.in_memory_hitl_case_repository import (
    InMemoryHITLCaseRepository,
)


# ============================================================
# DEMO CONFIGURATION
# ============================================================

# Keep evidence permanently so it can be opened after the demo.
EVIDENCE_OUTPUT_DIR = "outputs/evidence_demo"


# ============================================================
# MAIN DEMO
# ============================================================

async def main():

    print("\n" + "=" * 70)
    print("AGENTIC 3-WAY MATCHING POC")
    print("=" * 70)

    # ========================================================
    # 1. DOCUMENT INTAKE
    # ========================================================

    print("\n[1] DOCUMENT INTAKE")

    loaded = DocumentSetLoader().load()
    documents = loaded["documents"]
    contracts = loaded["contracts"]
    purchase_orders = loaded["purchase_orders"]
    invoices = loaded["invoices"]

    for contract_doc in documents["contracts"]:
        print(f"Contract : {contract_doc['filename']}")

    for po_doc in documents["purchase_orders"]:
        print(f"PO       : {po_doc['filename']}")

    for invoice_doc in documents["invoices"]:
        print(f"Invoice  : {invoice_doc['filename']}")

    # ========================================================
    # 2. DOCUMENT EXTRACTION
    # ========================================================

    print("\n[2] DOCUMENT EXTRACTION")

    for contract_data in loaded["extracted"]["contracts"]:
        print(
            "Contract extracted:",
            contract_data["contract_number"]["value"],
        )

    for po_data in loaded["extracted"]["purchase_orders"]:
        print(
            "PO extracted:",
            po_data["po_number"]["value"],
        )

    for invoice_data in loaded["extracted"]["invoices"]:
        print(
            "Invoice extracted:",
            invoice_data["invoice_number"]["value"],
        )

    # ========================================================
    # 3. CANONICALIZATION
    # ========================================================

    print("\n[3] CANONICALIZATION")

    for contract in contracts:
        print("Contract model :", contract.contract_number)
        print("Contract lines :", len(contract.line_items))

    for purchase_order in purchase_orders:
        print("PO model       :", purchase_order.po_number)
        print("PO lines       :", len(purchase_order.line_items))

    for invoice in invoices:
        print("Invoice model  :", invoice.invoice_number)
        print("Invoice lines  :", len(invoice.line_items))

    # ========================================================
    # 4. SHOW CANONICAL LINE ITEMS
    # ========================================================

    print("\n[4] CANONICAL LINE ITEMS")

    for contract in contracts:

        print(f"\nContract {contract.contract_number}:")

        for line in contract.line_items:
            print(
                f"  {line.item_code} | "
                f"{line.description} | "
                f"Qty={line.quantity} | "
                f"Price={line.unit_price}"
            )

    for purchase_order in purchase_orders:

        print(f"\nPurchase Order {purchase_order.po_number}:")

        for line in purchase_order.line_items:
            print(
                f"  {line.item_code} | "
                f"{line.description} | "
                f"Qty={line.quantity} | "
                f"Price={line.unit_price}"
            )

    for invoice in invoices:

        print(f"\nInvoice {invoice.invoice_number}:")

        for line in invoice.line_items:
            print(
                f"  {line.item_code} | "
                f"{line.description} | "
                f"Qty={line.quantity} | "
                f"Price={line.unit_price}"
            )

    # ========================================================
    # 5. DETERMINISTIC MATCHING + WHOLE-ROW EVIDENCE
    # ========================================================

    print(
        "\n[5] DETERMINISTIC MATCHING"
    )

    evidence_generator = EvidenceGenerator(
        output_dir=EVIDENCE_OUTPUT_DIR
    )

    engine = MatchingEngine(
        evidence_generator=evidence_generator
    )

    deterministic_result = engine.match_many(
        contracts,
        purchase_orders,
        invoices,
    )

    print(
        "\nDeterministic Matching Status:",
        deterministic_result.status,
    )

    # ========================================================
    # 7. DISPLAY DETERMINISTIC EXCEPTIONS
    # ========================================================

    print("\nDeterministic Exceptions:")

    if not deterministic_result.exceptions:

        print(
            "  No exceptions found."
        )

    else:

        for exception in (
            deterministic_result.exceptions
        ):

            print(
                f"\n  Type     : {exception.type}"
            )

            print(
                f"  Item     : {exception.item_code}"
            )

            print(
                f"  Field    : {exception.field}"
            )

            print(
                f"  Expected : {exception.expected}"
            )

            print(
                f"  Actual   : {exception.actual}"
            )

            if getattr(
                exception,
                "tolerance",
                None,
            ) is not None:

                print(
                    f"  Tolerance: "
                    f"{exception.tolerance}"
                )

            # ------------------------------------------------
            # Show generated evidence
            # ------------------------------------------------

            if exception.evidence:

                print(
                    "  Evidence:"
                )

                for evidence in exception.evidence:

                    print(
                        f"    Field : "
                        f"{evidence.get('field')}"
                    )

                    print(
                        f"    Page  : "
                        f"{evidence.get('page_number')}"
                    )

                    print(
                        f"    Image : "
                        f"{evidence.get('snip_path')}"
                    )

            else:

                print(
                    "  Evidence: NOT GENERATED"
                )

    # ========================================================
    # 8. PREPARE DETERMINISTIC RESULT FOR MAF AGENT
    # ========================================================

    print(
        "\n[6] PREPARING RESULT FOR MAF AGENT"
    )

    deterministic_result_for_agent = {
        "status": str(
            deterministic_result.status
        ),
        "exceptions": [],
    }

    for exception in (
        deterministic_result.exceptions
    ):

        exception_data = {
            "type": str(exception.type),
            "item_code": exception.item_code,
            "field": str(exception.field),
            "expected": exception.expected,
            "actual": exception.actual,
        }

        tolerance = getattr(
            exception,
            "tolerance",
            None,
        )

        if tolerance is not None:
            exception_data["tolerance"] = tolerance

        deterministic_result_for_agent[
            "exceptions"
        ].append(exception_data)

    print(
        json.dumps(
            deterministic_result_for_agent,
            indent=2,
            default=str,
        )
    )

    # ========================================================
    # 9. START MAF AGENT
    # ========================================================

    print(
        "\n[7] STARTING MAF AGENT"
    )

    agent = create_matching_agent()

    # ========================================================
    # 10. AGENT EXPLANATION
    # ========================================================

    prompt = f"""
You are the orchestration and explanation agent for
a contract, purchase order, and invoice 3-way matching
workflow.

The deterministic matching engine has already executed.

IMPORTANT:

The deterministic result below is authoritative.

Do NOT recalculate the values.

Do NOT change the status.

Do NOT invent additional exceptions.

Do NOT claim that the documents passed if the status
is EXCEPTION.

Your job is to explain the deterministic result to
a business user.

Deterministic Matching Result:

{json.dumps(
    deterministic_result_for_agent,
    indent=2,
    default=str,
)}

Provide your response using this structure:

OVERALL STATUS:
State PASS or EXCEPTION.

EXCEPTIONS:
List every exception returned by the deterministic
matching engine.

DETAILS:
For every exception explain:
- Exception type
- Item code
- Field
- Expected value
- Actual value
- Tolerance, if available

BUSINESS IMPACT:
Explain what the discrepancy means for the
Contract, Purchase Order, and Invoice.

RECOMMENDED ACTION:
If the status is EXCEPTION, state that the case
should be reviewed by a human.

HITL STATUS:
State that the exception has been routed to
Human-in-the-Loop review.
Do not invent a human decision.
"""

    print(
        "\n[8] RUNNING MAF AGENT EXPLANATION"
    )

    response = await agent.run(prompt)

    # ========================================================
    # 11. HITL ROUTING + PERSISTENCE
    # ========================================================

    print(
        "\n[9] HITL ROUTING"
    )

    repository = (
        InMemoryHITLCaseRepository()
    )

    hitl_service = HITLCaseService(
        repository=repository,
        routing_capability=HITLRoutingCapability(),
        decision_capability=HITLDecisionCapability(),
    )

    hitl_case = hitl_service.create_case(
        deterministic_result
    )

    if hitl_case is None:

        print(
            "  No HITL case created."
        )

    else:

        print(
            f"  Case ID : {hitl_case.case_id}"
        )

        print(
            f"  Status  : {hitl_case.status.value}"
        )

        print(
            f"  Evidence count : "
            f"{len(hitl_case.evidence)}"
        )

        for evidence in hitl_case.evidence:

            print(
                f"  Evidence image : "
                f"{evidence.get('snip_path')}"
            )

    # ========================================================
    # 12. SIMULATE HUMAN REVIEW
    # ========================================================

    if hitl_case is not None:

        print(
            "\n[10] HUMAN-IN-THE-LOOP REVIEW"
        )

        print(
            "  Case is now waiting for human review."
        )

        print(
            f"  Case ID : {hitl_case.case_id}"
        )

        print(
            f"  Status  : {hitl_case.status.value}"
        )

        print(
            "\n  Exception details:"
        )

        for exception in (
            hitl_case.validation_result.exceptions
        ):

            print(
                f"    {exception.type} | "
                f"{exception.item_code} | "
                f"{exception.field} | "
                f"Expected={exception.expected} | "
                f"Actual={exception.actual}"
            )

        print(
            "\n  Whole-row evidence:"
        )

        for evidence in hitl_case.evidence:

            print(
                f"    {evidence.get('snip_path')}"
            )

        # ----------------------------------------------------
        # Controlled human decision for POC demonstration
        # ----------------------------------------------------
        # ============================================================
        # HUMAN-IN-THE-LOOP REVIEW
        # ============================================================
        
        print()
        print("=" * 60)
        print("HUMAN REVIEW REQUIRED")
        print("=" * 60)
        
        print(
            f"Case ID : {hitl_case.case_id}"
        )
        
        print(
            f"Status  : {hitl_case.status.value}"
        )
        
        print()
        print("Review the generated evidence image(s):")
        
        for evidence in hitl_case.evidence:
            print(
                f"  {evidence.get('snip_path')}"
            )
        
        print()
        print(
            "The case is currently PENDING."
        )
        
        print(
            "Type APPROVED and press Enter "
            "to complete the human review."
        )
        
        print(
            "The program will NOT continue automatically."
        )
        
        while True:
        
            reviewer_input = input(
                "\nReviewer input: "
            ).strip()
        
            if reviewer_input.upper() == "APPROVED":
                break
            
            print(
                "Invalid input."
            )
        
            print(
                "Please type APPROVED."
            )
        
        
        print()
        print("✓ APPROVED received from reviewer.")
        
        decision = HITLDecision(
            decision=HITLDecisionType.APPROVE,
            reviewer="reviewer-001",
            comment=(
                "Invoice reviewed and "
                "commercially approved."
            ),
            timestamp=datetime.now(timezone.utc),
        )
        
        reviewed_case = (
            hitl_service.apply_decision(
                hitl_case.case_id,
                decision,
            )
        )
        
        print(
            f"Final Status : "
            f"{reviewed_case.status.value}"
        )
        # ----------------------------------------------------
        # Recover case from repository
        # ----------------------------------------------------

        recovered_case = (
            hitl_service.get_case(
                hitl_case.case_id
            )
        )

        print(
            f"\n  Final Status : "
            f"{recovered_case.status.value}"
        )

        print(
            f"  Decision     : "
            f"{recovered_case.decision.decision.value}"
        )

        print(
            f"  Reviewer     : "
            f"{recovered_case.reviewer}"
        )

        print(
            f"  Comment      : "
            f"{recovered_case.decision.comment}"
        )

    # ========================================================
    # 13. FINAL AGENT RESULT
    # ========================================================

    print("\n" + "=" * 70)
    print("FINAL AGENT RESULT")
    print("=" * 70)

    print(response.text)

    # ========================================================
    # 14. DEMO SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("DEMO FLOW COMPLETED")
    print("=" * 70)

    print(
        "Real documents        : PASS"
    )

    print(
        "Document extraction    : PASS"
    )

    print(
        "Canonicalization       : PASS"
    )

    print(
        "Deterministic matching :",
        deterministic_result.status,
    )

    print(
        "Whole-row evidence     :",
        "PASS"
        if any(
            exception.evidence
            for exception in (
                deterministic_result.exceptions
            )
        )
        else "NOT GENERATED",
    )

    print(
        "MAF agent explanation  : PASS"
    )

    print(
        "HITL routing           :",
        "PASS"
        if hitl_case is not None
        else "NOT REQUIRED",
    )

    if hitl_case is not None:

        print(
            "HITL initial status    :",
            hitl_case.status.value,
        )

        print(
            "Human decision         :",
            hitl_case.decision.decision.value
            if hitl_case.decision
            else "PENDING",
        )

        print(
            "HITL final status      :",
            hitl_case.status.value,
        )

    print(
        "Evidence output        :",
        EVIDENCE_OUTPUT_DIR,
    )

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
