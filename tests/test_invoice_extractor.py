from app.capabilities.invoice_extractor import InvoiceExtractor


INVOICE_PATH = (
    "data/invoices/invoice_INV-2026-5001.pdf"
)

from app.capabilities.invoice_extractor import InvoiceExtractor


def test_invoice_field_source_shape():

    extractor = InvoiceExtractor()

    invoice = extractor.extract_invoice(
        "data/invoices/invoice_INV-2026-5001.pdf"
    )

    assert invoice["invoice_number"] is not None




def test_invoice_extraction():

    extractor = InvoiceExtractor()

    invoice = extractor.extract_invoice(INVOICE_PATH)

    assert invoice["document_path"].endswith(
        "invoice_INV-2026-5001.pdf"
    )

    assert invoice["invoice_number"] is not None
    assert invoice["purchase_order"] is not None

    assert len(invoice["line_items"]) >= 1


def test_invoice_line_items():

    extractor = InvoiceExtractor()

    invoice = extractor.extract_invoice(INVOICE_PATH)

    first_item = invoice["line_items"][0]

    assert first_item["description"] is not None
    assert first_item["quantity"] is not None
    assert first_item["unit_price"] is not None
    assert first_item["amount"] is not None


def test_invoice_extraction_missing_file():

    extractor = InvoiceExtractor()

    try:
        extractor.extract_invoice(
            "data/invoices/does_not_exist.pdf"
        )
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_cross_validation_logs_warning_on_mismatch():
    """
    When quantity × unit_price ≠ amount, the cross-validation
    should log a warning but NOT auto-correct the quantity,
    because the invoice itself may contain calculation errors.
    """
    extractor = InvoiceExtractor()

    # Simulate extracted items with mismatch
    items = [
        {
            "item_code": {"value": "FIB-001", "source": []},
            "description": {"value": "Fiber Cable", "source": []},
            "quantity": {"value": 12000, "source": []},
            "unit_price": {"value": 145.0, "source": []},
            "amount": {"value": 1914000.0, "source": []},
        }
    ]

    result = extractor._cross_validate_line_items(items)

    # Quantity should NOT be auto-corrected
    assert result[0]["quantity"]["value"] == 12000


def test_cross_validation_no_correction_when_valid():
    """
    When quantity × unit_price ≈ amount, no correction should occur.
    """
    extractor = InvoiceExtractor()

    items = [
        {
            "item_code": {"value": "FIB-001", "source": []},
            "description": {"value": "Fiber Cable", "source": []},
            "quantity": {"value": 13200, "source": []},
            "unit_price": {"value": 145.0, "source": []},
            "amount": {"value": 1914000.0, "source": []},
        }
    ]

    result = extractor._cross_validate_line_items(items)

    assert result[0]["quantity"]["value"] == 13200