from app.matching.line_presence_validator import (
    LinePresenceValidator,
)
from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder


def create_documents():
    contract = Contract(
        contract_id="CON-2026-TEL-004",
        contract_number="CON-2026-TEL-004",
        quantity_tolerance="+0%",
        price_tolerance="±2%",
        line_items=[
            LineItem(
                item_code="OSS-001",
                description=(
                    "Network Monitoring Software License"
                ),
                quantity=50,
                unit="License",
                unit_price=32000.0,
            ),
            LineItem(
                item_code="OSS-002",
                description=(
                    "Fault Management Module"
                ),
                quantity=20,
                unit="License",
                unit_price=45000.0,
            ),
            LineItem(
                item_code="OSS-003",
                description=(
                    "Performance Analytics Module"
                ),
                quantity=10,
                unit="License",
                unit_price=58000.0,
            ),
        ],
    )

    purchase_order = PurchaseOrder(
        po_id="PO-2026-TEL-1004",
        po_number="PO-2026-TEL-1004",
        contract_reference="CON-2026-TEL-004",
        line_items=[
            LineItem(
                item_code="OSS-001",
                description=(
                    "Network Monitoring Software License"
                ),
                quantity=50,
                unit="License",
                unit_price=32000.0,
            ),
            LineItem(
                item_code="OSS-002",
                description=(
                    "Fault Management Module"
                ),
                quantity=20,
                unit="License",
                unit_price=45000.0,
            ),
            LineItem(
                item_code="OSS-003",
                description=(
                    "Performance Analytics Module"
                ),
                quantity=10,
                unit="License",
                unit_price=58000.0,
            ),
        ],
    )

    invoice = Invoice(
        invoice_id="INV-2026-TEL-5004",
        invoice_number="INV-2026-TEL-5004",
        purchase_order_reference="PO-2026-TEL-1004",
        line_items=[
            LineItem(
                item_code="OSS-001",
                description=(
                    "Network Monitoring Software License"
                ),
                quantity=50,
                unit="License",
                unit_price=32000.0,
            ),
            LineItem(
                item_code="OSS-002",
                description=(
                    "Fault Management Module"
                ),
                quantity=20,
                unit="License",
                unit_price=45000.0,
            ),
        ],
    )

    return contract, purchase_order, invoice


def test_passes_when_all_lines_present():
    contract, purchase_order, invoice = (
        create_documents()
    )

    invoice.line_items.append(
        LineItem(
            item_code="OSS-003",
            description=(
                "Performance Analytics Module"
            ),
            quantity=10,
            unit="License",
            unit_price=58000.0,
        )
    )

    result = LinePresenceValidator().validate_group(
        contract,
        [purchase_order],
        [invoice],
    )

    assert result.status == "PASS"
    assert result.exceptions == []


def test_detects_line_missing_from_invoice():
    contract, purchase_order, invoice = (
        create_documents()
    )

    result = LinePresenceValidator().validate_group(
        contract,
        [purchase_order],
        [invoice],
    )

    assert result.status == "EXCEPTION"
    assert len(result.exceptions) == 1

    exception = result.exceptions[0]

    assert exception.type == "MISSING_LINE"
    assert exception.item_code == "OSS-003"
    assert exception.field == "presence"
    assert (
        exception.source
        is purchase_order.line_items[2].source
    )


def test_missing_line_requires_contract_and_po():
    contract, purchase_order, invoice = (
        create_documents()
    )

    contract.line_items = [
        item
        for item in contract.line_items
        if item.item_code != "OSS-003"
    ]

    result = LinePresenceValidator().validate_group(
        contract,
        [purchase_order],
        [invoice],
    )

    assert result.status == "PASS"


def test_detects_unmatched_invoice_line():
    contract, purchase_order, invoice = (
        create_documents()
    )

    invoice.line_items.append(
        LineItem(
            item_code="OSS-001\nOSS-002\nOSS-003",
            description="Merged extraction row",
            quantity=20,
            unit="License",
            unit_price=45000.0,
        )
    )

    result = LinePresenceValidator().validate_group(
        contract,
        [purchase_order],
        [invoice],
    )

    assert result.status == "EXCEPTION"

    unmatched = [
        exception
        for exception in result.exceptions
        if exception.type == "UNMATCHED_LINE"
    ]

    assert len(unmatched) == 1

    exception = unmatched[0]

    assert exception.item_code == (
        "OSS-001\nOSS-002\nOSS-003"
    )
    assert exception.field == "item_code"


def test_no_missing_line_when_po_lacks_item():
    contract, purchase_order, invoice = (
        create_documents()
    )

    purchase_order.line_items = [
        item
        for item in purchase_order.line_items
        if item.item_code != "OSS-003"
    ]

    result = LinePresenceValidator().validate_group(
        contract,
        [purchase_order],
        [invoice],
    )

    assert result.status == "PASS"
