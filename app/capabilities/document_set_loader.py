from typing import Any

from app.canonicalization.canonicalizer import Canonicalizer
from app.capabilities.contract_extractor import ContractExtractor
from app.capabilities.document_intake import DocumentIntake
from app.capabilities.invoice_extractor import InvoiceExtractor
from app.capabilities.purchase_order_extractor import (
    PurchaseOrderExtractor,
)
from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.storage.document_storage import DocumentStorage


class DocumentSetLoader:
    """
    Discovers, extracts, and canonicalizes every contract,
    purchase order, and invoice in configured storage.
    """

    def __init__(
        self,
        storage: DocumentStorage | None = None,
        intake: DocumentIntake | None = None,
    ):
        self.intake = intake or (
            DocumentIntake(storage=storage)
            if storage is not None
            else DocumentIntake.from_env()
        )
        self.storage = self.intake.storage
        self.canonicalizer = Canonicalizer()
        self.contract_extractor = ContractExtractor(
            storage=self.storage
        )
        self.purchase_order_extractor = PurchaseOrderExtractor(
            storage=self.storage
        )
        self.invoice_extractor = InvoiceExtractor(
            storage=self.storage
        )

    def load(
        self,
    ) -> dict[str, Any]:
        documents = self.intake.discover_documents()

        if not documents.get("contracts"):
            raise RuntimeError("No contract document found.")

        if not documents.get("purchase_orders"):
            raise RuntimeError("No purchase order document found.")

        if not documents.get("invoices"):
            raise RuntimeError("No invoice document found.")

        contracts: list[Contract] = []
        purchase_orders: list[PurchaseOrder] = []
        invoices: list[Invoice] = []

        extracted_contracts = []
        extracted_purchase_orders = []
        extracted_invoices = []

        for document in documents["contracts"]:
            extracted = self.contract_extractor.extract_contract(
                document["path"]
            )
            extracted_contracts.append(extracted)
            contracts.append(
                self.canonicalizer.canonicalize_contract(
                    extracted,
                    document_id=document["document_id"],
                )
            )

        for document in documents["purchase_orders"]:
            extracted = (
                self.purchase_order_extractor.extract_purchase_order(
                    document["path"]
                )
            )
            extracted_purchase_orders.append(extracted)
            purchase_orders.append(
                self.canonicalizer.canonicalize_purchase_order(
                    extracted,
                    document_id=document["document_id"],
                )
            )

        for document in documents["invoices"]:
            extracted = self.invoice_extractor.extract_invoice(
                document["path"]
            )
            extracted_invoices.append(extracted)
            invoices.append(
                self.canonicalizer.canonicalize_invoice(
                    extracted,
                    document_id=document["document_id"],
                )
            )

        return {
            "documents": documents,
            "extracted": {
                "contracts": extracted_contracts,
                "purchase_orders": extracted_purchase_orders,
                "invoices": extracted_invoices,
            },
            "contracts": contracts,
            "purchase_orders": purchase_orders,
            "invoices": invoices,
        }
