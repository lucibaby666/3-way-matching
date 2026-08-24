from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.validation_result import (
    ValidationException,
    ValidationResult,
)
from app.matching.quantity_validator import (
    items_by_code,
)


class LinePresenceValidator:
    def validate(
        self,
        contract: Contract,
        purchase_order: PurchaseOrder,
        invoice: Invoice,
    ) -> ValidationResult:
        return self.validate_group(
            contract,
            [purchase_order],
            [invoice],
        )

    def validate_group(
        self,
        contract: Contract | None,
        purchase_orders: list[PurchaseOrder],
        invoices: list[Invoice],
    ) -> ValidationResult:
        exceptions = []

        contract_items = items_by_code(
            contract.line_items if contract else []
        )

        purchase_order_items: dict[
            str,
            list,
        ] = {}

        for purchase_order in purchase_orders:
            for item in purchase_order.line_items:

                if item.item_code is None:
                    continue

                purchase_order_items.setdefault(
                    item.item_code,
                    [],
                ).append(item)

        invoice_codes: set[str] = set()

        for invoice in invoices:
            invoice_codes.update(
                items_by_code(invoice.line_items)
            )

        all_item_codes = (
            set(contract_items)
            | set(purchase_order_items)
            | invoice_codes
        )

        for item_code in sorted(all_item_codes):

            contract_item = contract_items.get(
                item_code
            )

            po_matches = (
                purchase_order_items.get(item_code)
            )

            if contract_item is None:
                continue

            if not po_matches:
                continue

            if item_code in invoice_codes:
                continue

            exceptions.append(
                ValidationException(
                    type="MISSING_LINE",
                    field="presence",
                    item_code=item_code,
                    expected=(
                        "invoiced against "
                        "purchase order"
                    ),
                    actual=(
                        "not present on any "
                        "invoice"
                    ),
                    tolerance=None,
                    source=(
                        po_matches[0].source
                    ),
                )
            )

        known_item_codes = (
            set(contract_items)
            | set(purchase_order_items)
        )

        for invoice in invoices:
            for item in invoice.line_items:

                if item.item_code is None:
                    continue

                if item.item_code in known_item_codes:
                    continue

                exceptions.append(
                    ValidationException(
                        type="UNMATCHED_LINE",
                        field="item_code",
                        item_code=item.item_code,
                        expected=(
                            "item code defined on "
                            "contract or purchase "
                            "order"
                        ),
                        actual=item.item_code,
                        tolerance=None,
                        source=item.source,
                    )
                )

        return ValidationResult(
            status=(
                "EXCEPTION"
                if exceptions
                else "PASS"
            ),
            exceptions=exceptions,
        )
