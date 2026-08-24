from app.models.contract import Contract
from app.models.purchase_order import PurchaseOrder
from app.models.invoice import Invoice
from app.models.validation_result import (
    ValidationException,
    ValidationResult,
)


class RelationshipValidator:
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

        contract_number = (
            contract.contract_number
            if contract is not None
            else None
        )

        for purchase_order in purchase_orders:
            if (
                purchase_order.contract_reference
                != contract_number
            ):
                exceptions.append(
                    ValidationException(
                        type="CONTRACT_REFERENCE_MISMATCH",
                        field="contract_reference",
                        expected=contract_number,
                        actual=purchase_order.contract_reference,
                        source=purchase_order.source,
                    )
                )

        po_numbers = {
            purchase_order.po_number
            for purchase_order in purchase_orders
            if purchase_order.po_number
        }

        for invoice in invoices:
            if invoice.purchase_order_reference not in po_numbers:
                if len(po_numbers) == 1:
                    expected = next(iter(po_numbers))
                elif len(po_numbers) > 1:
                    expected = sorted(po_numbers)
                else:
                    expected = None

                exceptions.append(
                    ValidationException(
                        type="PO_REFERENCE_MISMATCH",
                        field="purchase_order_reference",
                        expected=expected,
                        actual=invoice.purchase_order_reference,
                        source=invoice.source,
                    )
                )

        return ValidationResult(
            status="EXCEPTION" if exceptions else "PASS",
            exceptions=exceptions,
        )
