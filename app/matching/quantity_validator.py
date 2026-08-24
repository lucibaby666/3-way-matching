from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.models.validation_result import (
    ValidationException,
    ValidationResult,
)


def invoices_for_purchase_order(
    purchase_order: PurchaseOrder,
    invoices: list[Invoice],
    purchase_orders: list[PurchaseOrder],
) -> list[Invoice]:
    matched = [
        invoice
        for invoice in invoices
        if invoice.purchase_order_reference
        == purchase_order.po_number
    ]

    if matched:
        return matched

    if len(purchase_orders) == 1:
        return list(invoices)

    return []


def items_by_code(
    line_items: list[LineItem],
) -> dict[str, LineItem]:
    return {
        item.item_code: item
        for item in line_items
        if item.item_code is not None
    }


class QuantityValidator:
    def validate(
        self,
        contract: Contract,
        purchase_order: PurchaseOrder,
        invoice: Invoice,
        line_matches: list[dict],
    ) -> ValidationResult:
        exceptions = []

        quantity_tolerance = self._parse_percentage(
            contract.quantity_tolerance
        )

        for match in line_matches:
            item_code = match["item_code"]

            contract_item = match["contract"]
            purchase_order_item = match["purchase_order"]
            invoice_item = match["invoice"]

            if (
                contract_item is not None
                and purchase_order_item is not None
            ):
                allowed_quantity = contract_item.quantity * (
                    1 + quantity_tolerance / 100
                )

                if purchase_order_item.quantity > allowed_quantity:
                    exceptions.append(
                        ValidationException(
                            type="QUANTITY_MISMATCH",
                            field="quantity",
                            item_code=item_code,
                            expected=allowed_quantity,
                            actual=purchase_order_item.quantity,
                            tolerance=contract.quantity_tolerance,
                            source=purchase_order_item.source,
                        )
                    )

            if (
                purchase_order_item is not None
                and invoice_item is not None
            ):
                if invoice_item.quantity > purchase_order_item.quantity:
                    exceptions.append(
                        ValidationException(
                            type="QUANTITY_MISMATCH",
                            item_code=item_code,
                            field="quantity",
                            expected=purchase_order_item.quantity,
                            actual=invoice_item.quantity,
                            tolerance=None,
                            source=invoice_item.source,
                        )
                    )

        return ValidationResult(
            status="EXCEPTION" if exceptions else "PASS",
            exceptions=exceptions,
        )

    def validate_group(
        self,
        contract: Contract | None,
        purchase_orders: list[PurchaseOrder],
        invoices: list[Invoice],
    ) -> ValidationResult:
        exceptions = []

        quantity_tolerance = self._parse_percentage(
            contract.quantity_tolerance if contract else None
        )

        contract_items = items_by_code(
            contract.line_items if contract else []
        )

        item_codes: set[str] = set(contract_items)

        for purchase_order in purchase_orders:
            item_codes.update(
                items_by_code(purchase_order.line_items)
            )

        for invoice in invoices:
            item_codes.update(
                items_by_code(invoice.line_items)
            )

        for item_code in sorted(item_codes):
            contract_item = contract_items.get(item_code)

            po_items = [
                item
                for purchase_order in purchase_orders
                for item in purchase_order.line_items
                if item.item_code == item_code
            ]

            if contract_item is not None and po_items:
                po_quantity = sum(
                    item.quantity or 0
                    for item in po_items
                )

                allowed_quantity = contract_item.quantity * (
                    1 + quantity_tolerance / 100
                )

                if po_quantity > allowed_quantity:
                    exceptions.append(
                        ValidationException(
                            type="QUANTITY_MISMATCH",
                            field="quantity",
                            item_code=item_code,
                            expected=allowed_quantity,
                            actual=po_quantity,
                            tolerance=(
                                contract.quantity_tolerance
                                if contract
                                else None
                            ),
                            source=po_items[0].source,
                        )
                    )

            for purchase_order in purchase_orders:
                po_item = items_by_code(
                    purchase_order.line_items
                ).get(item_code)

                related_invoices = invoices_for_purchase_order(
                    purchase_order,
                    invoices,
                    purchase_orders,
                )

                invoice_items = [
                    item
                    for invoice in related_invoices
                    for item in invoice.line_items
                    if item.item_code == item_code
                ]

                if po_item is not None and invoice_items:
                    invoice_quantity = sum(
                        item.quantity or 0
                        for item in invoice_items
                    )

                    if invoice_quantity > po_item.quantity:
                        exceptions.append(
                            ValidationException(
                                type="QUANTITY_MISMATCH",
                                item_code=item_code,
                                field="quantity",
                                expected=po_item.quantity,
                                actual=invoice_quantity,
                                tolerance=None,
                                source=invoice_items[0].source,
                            )
                        )

        return ValidationResult(
            status="EXCEPTION" if exceptions else "PASS",
            exceptions=exceptions,
        )

    @staticmethod
    def _parse_percentage(value: str | None) -> float:
        if not value:
            return 0.0

        value = (
            value
            .strip()
            .replace("%", "")
            .replace("±", "")
        )

        return float(value)
