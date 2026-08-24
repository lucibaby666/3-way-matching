from dataclasses import dataclass

from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder


@dataclass
class MatchingGroup:
    contract: Contract | None
    purchase_orders: list[PurchaseOrder]
    invoices: list[Invoice]


class DocumentGrouper:
    """
    Groups contracts, purchase orders, and invoices by
    document references so multiple input files can be
    matched as related sets.
    """

    def group(
        self,
        contracts: list[Contract],
        purchase_orders: list[PurchaseOrder],
        invoices: list[Invoice],
    ) -> list[MatchingGroup]:
        used_po_ids: set[str] = set()
        used_invoice_ids: set[str] = set()
        groups: list[MatchingGroup] = []

        for contract in contracts:
            related_pos = [
                purchase_order
                for purchase_order in purchase_orders
                if purchase_order.contract_reference
                == contract.contract_number
                and purchase_order.po_id not in used_po_ids
            ]

            for purchase_order in related_pos:
                used_po_ids.add(purchase_order.po_id)

            po_numbers = {
                purchase_order.po_number
                for purchase_order in related_pos
                if purchase_order.po_number
            }

            related_invoices = [
                invoice
                for invoice in invoices
                if invoice.purchase_order_reference in po_numbers
                and invoice.invoice_id not in used_invoice_ids
            ]

            for invoice in related_invoices:
                used_invoice_ids.add(invoice.invoice_id)

            if not related_pos and not related_invoices:
                continue

            groups.append(
                MatchingGroup(
                    contract=contract,
                    purchase_orders=related_pos,
                    invoices=related_invoices,
                )
            )

        orphan_pos = [
            purchase_order
            for purchase_order in purchase_orders
            if purchase_order.po_id not in used_po_ids
        ]

        for purchase_order in orphan_pos:
            related_invoices = [
                invoice
                for invoice in invoices
                if invoice.purchase_order_reference
                == purchase_order.po_number
                and invoice.invoice_id not in used_invoice_ids
            ]

            for invoice in related_invoices:
                used_invoice_ids.add(invoice.invoice_id)

            groups.append(
                MatchingGroup(
                    contract=None,
                    purchase_orders=[purchase_order],
                    invoices=related_invoices,
                )
            )

        orphan_invoices = [
            invoice
            for invoice in invoices
            if invoice.invoice_id not in used_invoice_ids
        ]

        for invoice in orphan_invoices:
            groups.append(
                MatchingGroup(
                    contract=None,
                    purchase_orders=[],
                    invoices=[invoice],
                )
            )

        return groups
