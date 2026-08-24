from app.models.contract import Contract
from app.models.purchase_order import PurchaseOrder
from app.models.invoice import Invoice
from app.models.validation_result import (
    ValidationException,
    ValidationResult,
)
from app.matching.quantity_validator import (
    invoices_for_purchase_order,
    items_by_code,
)


class PriceValidator:
    def validate(
        self,
        contract: Contract,
        purchase_order: PurchaseOrder,
        invoice: Invoice,
        line_matches: list[dict],
    ) -> ValidationResult:
        exceptions = []

        price_tolerance = self._parse_percentage(
            contract.price_tolerance
        )

        for match in line_matches:
            item_code = match["item_code"]

            contract_item = match["contract"]
            purchase_order_item = match["purchase_order"]
            invoice_item = match["invoice"]

            # Contract → PO price validation
            if (
                contract_item is not None
                and purchase_order_item is not None
            ):
                minimum_price = contract_item.unit_price * (
                    1 - price_tolerance / 100
                )

                maximum_price = contract_item.unit_price * (
                    1 + price_tolerance / 100
                )

                if not (
                    minimum_price
                    <= purchase_order_item.unit_price
                    <= maximum_price
                ):
                    exceptions.append(
                        ValidationException(
                            type="PRICE_MISMATCH",
                            field="unit_price",
                            item_code=item_code,
                            expected={
                                "min": minimum_price,
                                "max": maximum_price,
                            },
                            actual=purchase_order_item.unit_price,
                            tolerance=contract.price_tolerance,
                            source=purchase_order_item.source,
                        )
                    )

            # PO → Invoice price validation
            if (
                purchase_order_item is not None
                and invoice_item is not None
            ):
                if (
                    invoice_item.unit_price
                    > purchase_order_item.unit_price
                ):
                    exceptions.append(
                        ValidationException(
                            type="PRICE_MISMATCH",
                            item_code=item_code,
                            field="unit_price",
                            expected=purchase_order_item.unit_price,
                            actual=invoice_item.unit_price,
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

        price_tolerance = self._parse_percentage(
            contract.price_tolerance if contract else None
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

            for purchase_order in purchase_orders:
                po_item = items_by_code(
                    purchase_order.line_items
                ).get(item_code)

                if contract_item is not None and po_item is not None:
                    minimum_price = contract_item.unit_price * (
                        1 - price_tolerance / 100
                    )

                    maximum_price = contract_item.unit_price * (
                        1 + price_tolerance / 100
                    )

                    if not (
                        minimum_price
                        <= po_item.unit_price
                        <= maximum_price
                    ):
                        exceptions.append(
                            ValidationException(
                                type="PRICE_MISMATCH",
                                field="unit_price",
                                item_code=item_code,
                                expected={
                                    "min": minimum_price,
                                    "max": maximum_price,
                                },
                                actual=po_item.unit_price,
                                tolerance=(
                                    contract.price_tolerance
                                    if contract
                                    else None
                                ),
                                source=po_item.source,
                            )
                        )

                related_invoices = invoices_for_purchase_order(
                    purchase_order,
                    invoices,
                    purchase_orders,
                )

                if po_item is None:
                    continue

                for invoice in related_invoices:
                    invoice_item = items_by_code(
                        invoice.line_items
                    ).get(item_code)

                    if invoice_item is None:
                        continue

                    if (
                        invoice_item.unit_price
                        > po_item.unit_price
                    ):
                        exceptions.append(
                            ValidationException(
                                type="PRICE_MISMATCH",
                                item_code=item_code,
                                field="unit_price",
                                expected=po_item.unit_price,
                                actual=invoice_item.unit_price,
                                tolerance=None,
                                source=invoice_item.source,
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