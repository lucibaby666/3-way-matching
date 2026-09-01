from app.matching.matching_engine import MatchingEngine
from app.models.contract import Contract
from app.models.purchase_order import PurchaseOrder
from app.models.invoice import Invoice
from app.models.line_item import LineItem


def create_documents(
    po_quantity=100,
    invoice_quantity=100,
    po_price=250.0,
    invoice_price=250.0,
    contract_reference="CON-2026-001",
    invoice_po_reference="PO-2026-1001",
):
    contract = Contract(
        contract_id="CON-2026-001",
        contract_number="CON-2026-001",
        quantity_tolerance="+5%",
        price_tolerance="±2%",
        line_items=[
            LineItem(
                item_code="ITM-001",
                description="Industrial Safety Gloves",
                quantity=100,
                unit="Pair",
                unit_price=250.0,
            )
        ],
    )

    purchase_order = PurchaseOrder(
        po_id="PO-2026-1001",
        po_number="PO-2026-1001",
        contract_reference=contract_reference,
        line_items=[
            LineItem(
                item_code="ITM-001",
                description="Industrial Safety Gloves",
                quantity=po_quantity,
                unit="Pair",
                unit_price=po_price,
            )
        ],
    )

    invoice = Invoice(
        invoice_id="INV-2026-5001",
        invoice_number="INV-2026-5001",
        purchase_order_reference=invoice_po_reference,
        line_items=[
            LineItem(
                item_code="ITM-001",
                description="Industrial Safety Gloves",
                quantity=invoice_quantity,
                unit="Pair",
                unit_price=invoice_price,
            )
        ],
    )

    return contract, purchase_order, invoice


# ============================================================
# POSITIVE TEST
# ============================================================

def test_matching_engine_passes_for_valid_documents():
    contract, purchase_order, invoice = create_documents()

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "PASS"
    assert result.exceptions == []


# ============================================================
# NEGATIVE — QUANTITY
# ============================================================

def test_matching_engine_detects_quantity_exception():
    contract, purchase_order, invoice = create_documents(
        po_quantity=106,
        invoice_quantity=106,
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"
    assert len(result.exceptions) == 1

    exception = result.exceptions[0]

    assert exception.type == "QUANTITY_MISMATCH"
    assert exception.item_code == "ITM-001"
    assert exception.expected == 105.0
    assert exception.actual == 106


# ============================================================
# NEGATIVE — PRICE
# ============================================================

def test_matching_engine_detects_price_exception():
    contract, purchase_order, invoice = create_documents(
        po_price=256.0,
        invoice_price=256.0,
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"
    assert len(result.exceptions) == 1

    exception = result.exceptions[0]

    assert exception.type == "PRICE_MISMATCH"
    assert exception.item_code == "ITM-001"
    assert exception.actual == 256.0


# ============================================================
# NEGATIVE — RELATIONSHIP
# ============================================================

def test_matching_engine_detects_relationship_exception():
    contract, purchase_order, invoice = create_documents(
        contract_reference="CON-2026-999",
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"
    assert len(result.exceptions) == 1

    exception = result.exceptions[0]

    assert exception.type == "CONTRACT_REFERENCE_MISMATCH"
    assert exception.expected == "CON-2026-001"
    assert exception.actual == "CON-2026-999"


# ============================================================
# NEGATIVE — MISSING LINE
# ============================================================

def test_matching_engine_detects_missing_invoice_line():
    contract, purchase_order, invoice = create_documents()

    invoice.line_items = []

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"
    assert len(result.exceptions) == 1

    exception = result.exceptions[0]

    assert exception.type == "MISSING_LINE"
    assert exception.item_code == "ITM-001"


# ============================================================
# NEGATIVE — MULTIPLE EXCEPTIONS
# ============================================================

def test_matching_engine_collects_multiple_exceptions():
    contract, purchase_order, invoice = create_documents(
        po_quantity=106,
        invoice_quantity=107,
        po_price=256.0,
        invoice_price=257.0,
        contract_reference="CON-2026-999",
        invoice_po_reference="PO-2026-9999",
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"

    assert len(result.exceptions) == 6

    exception_types = [
        exception.type
        for exception in result.exceptions
    ]

    assert exception_types.count(
        "CONTRACT_REFERENCE_MISMATCH"
    ) == 1

    assert exception_types.count(
        "PO_REFERENCE_MISMATCH"
    ) == 1

    assert exception_types.count(
        "QUANTITY_MISMATCH"
    ) == 2

    assert exception_types.count(
        "PRICE_MISMATCH"
    ) == 2


# ============================================================
# SCENARIO 2 — QUANTITY EXCEPTION
# FIB-001 invoice qty 13,200m vs PO 12,000m
# Contract tolerance ±5% → max allowed 12,600m
# ============================================================

def test_scenario_2_quantity_exception():
    contract = Contract(
        contract_id="CON-2026-TEL-002",
        contract_number="CON-2026-TEL-002",
        quantity_tolerance="±5%",
        price_tolerance="±2%",
        line_items=[
            LineItem(
                item_code="FIB-001",
                description="Single-Mode Fiber Cable",
                quantity=12000,
                unit="Meter",
                unit_price=145.0,
            )
        ],
    )

    purchase_order = PurchaseOrder(
        po_id="PO-2026-TEL-1002",
        po_number="PO-2026-TEL-1002",
        contract_reference="CON-2026-TEL-002",
        line_items=[
            LineItem(
                item_code="FIB-001",
                description="Single-Mode Fiber Cable",
                quantity=12000,
                unit="Meter",
                unit_price=145.0,
            )
        ],
    )

    invoice = Invoice(
        invoice_id="INV-2026-TEL-5002",
        invoice_number="INV-2026-TEL-5002",
        purchase_order_reference="PO-2026-TEL-1002",
        line_items=[
            LineItem(
                item_code="FIB-001",
                description="Single-Mode Fiber Cable",
                quantity=13200,
                unit="Meter",
                unit_price=145.0,
            )
        ],
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"

    quantity_exceptions = [
        e
        for e in result.exceptions
        if e.type == "QUANTITY_MISMATCH"
    ]
    assert len(quantity_exceptions) == 1

    exc = quantity_exceptions[0]
    assert exc.item_code == "FIB-001"
    assert exc.field == "quantity"
    assert exc.expected == 12000
    assert exc.actual == 13200
    assert exc.tolerance is None


# ============================================================
# SCENARIO 3 — PRICE EXCEPTION
# TWR-002 invoice rate INR 4,725 vs PO/contract INR 4,500
# Contract tolerance ±2% → max allowed INR 4,590
# ============================================================

def test_scenario_3_price_exception():
    contract = Contract(
        contract_id="CON-2026-TEL-003",
        contract_number="CON-2026-TEL-003",
        quantity_tolerance="±5%",
        price_tolerance="±2%",
        line_items=[
            LineItem(
                item_code="TWR-002",
                description="Telecom Tower Antenna",
                quantity=40,
                unit="Each",
                unit_price=4500.0,
            )
        ],
    )

    purchase_order = PurchaseOrder(
        po_id="PO-2026-TEL-1003",
        po_number="PO-2026-TEL-1003",
        contract_reference="CON-2026-TEL-003",
        line_items=[
            LineItem(
                item_code="TWR-002",
                description="Telecom Tower Antenna",
                quantity=40,
                unit="Each",
                unit_price=4500.0,
            )
        ],
    )

    invoice = Invoice(
        invoice_id="INV-2026-TEL-5003",
        invoice_number="INV-2026-TEL-5003",
        purchase_order_reference="PO-2026-TEL-1003",
        line_items=[
            LineItem(
                item_code="TWR-002",
                description="Telecom Tower Antenna",
                quantity=40,
                unit="Each",
                unit_price=4725.0,
            )
        ],
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"

    price_exceptions = [
        e
        for e in result.exceptions
        if e.type == "PRICE_MISMATCH"
    ]
    assert len(price_exceptions) == 1

    exc = price_exceptions[0]
    assert exc.item_code == "TWR-002"
    assert exc.field == "unit_price"
    assert exc.expected == 4500.0
    assert exc.actual == 4725.0
    assert exc.tolerance is None


# ============================================================
# SCENARIO 4 — MISSING INVOICE LINE
# OSS-003 exists on contract and PO but not on invoice
# ============================================================

def test_scenario_4_missing_invoice_line():
    contract = Contract(
        contract_id="CON-2026-TEL-004",
        contract_number="CON-2026-TEL-004",
        quantity_tolerance="±5%",
        price_tolerance="±2%",
        line_items=[
            LineItem(
                item_code="OSS-001",
                description="Network Monitoring Software License",
                quantity=50,
                unit="License",
                unit_price=32000.0,
            ),
            LineItem(
                item_code="OSS-002",
                description="Fault Management Module",
                quantity=20,
                unit="License",
                unit_price=45000.0,
            ),
            LineItem(
                item_code="OSS-003",
                description="Performance Analytics Module",
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
                description="Network Monitoring Software License",
                quantity=50,
                unit="License",
                unit_price=32000.0,
            ),
            LineItem(
                item_code="OSS-002",
                description="Fault Management Module",
                quantity=20,
                unit="License",
                unit_price=45000.0,
            ),
            LineItem(
                item_code="OSS-003",
                description="Performance Analytics Module",
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
                description="Network Monitoring Software License",
                quantity=50,
                unit="License",
                unit_price=32000.0,
            ),
            LineItem(
                item_code="OSS-002",
                description="Fault Management Module",
                quantity=20,
                unit="License",
                unit_price=45000.0,
            ),
        ],
    )

    result = MatchingEngine().match(
        contract,
        purchase_order,
        invoice,
    )

    assert result.status == "EXCEPTION"

    missing_line_exceptions = [
        e
        for e in result.exceptions
        if e.type == "MISSING_LINE"
    ]
    assert len(missing_line_exceptions) == 1

    exc = missing_line_exceptions[0]
    assert exc.item_code == "OSS-003"
    assert exc.field == "presence"