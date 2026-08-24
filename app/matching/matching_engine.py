import re

from app.capabilities.evidence_generator import (
    EvidenceGenerator,
)
from app.matching.document_grouper import (
    DocumentGrouper,
    MatchingGroup,
)
from app.matching.line_item_matcher import (
    LineItemMatcher,
)
from app.matching.line_presence_validator import (
    LinePresenceValidator,
)
from app.matching.price_validator import (
    PriceValidator,
)
from app.matching.quantity_validator import (
    QuantityValidator,
)
from app.matching.relationship_validator import (
    RelationshipValidator,
)
from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.validation_result import (
    ValidationException,
    ValidationResult,
)
from app.storage.locator import locator_stem


class MatchingEngine:
    def __init__(
        self,
        evidence_generator: EvidenceGenerator | None = None,
    ):
        self.relationship_validator = (
            RelationshipValidator()
        )

        self.line_presence_validator = (
            LinePresenceValidator()
        )

        self.line_item_matcher = (
            LineItemMatcher()
        )

        self.quantity_validator = (
            QuantityValidator()
        )

        self.price_validator = (
            PriceValidator()
        )

        self.evidence_generator = (
            evidence_generator
            or EvidenceGenerator()
        )

        self.document_grouper = DocumentGrouper()

    def match(
        self,
        contract: Contract,
        purchase_order: PurchaseOrder,
        invoice: Invoice,
    ) -> ValidationResult:
        return self._match_group(
            MatchingGroup(
                contract=contract,
                purchase_orders=[purchase_order],
                invoices=[invoice],
            )
        )

    def match_many(
        self,
        contracts: list[Contract],
        purchase_orders: list[PurchaseOrder],
        invoices: list[Invoice],
    ) -> ValidationResult:
        groups = self.document_grouper.group(
            contracts,
            purchase_orders,
            invoices,
        )

        exceptions: list[ValidationException] = []

        for group in groups:
            result = self._match_group(group)
            exceptions.extend(result.exceptions)

        return ValidationResult(
            status=(
                "EXCEPTION"
                if exceptions
                else "PASS"
            ),
            exceptions=exceptions,
        )

    def _match_group(
        self,
        group: MatchingGroup,
    ) -> ValidationResult:
        exceptions: list[ValidationException] = []

        relationship_result = (
            self.relationship_validator.validate_group(
                group.contract,
                group.purchase_orders,
                group.invoices,
            )
        )

        exceptions.extend(
            relationship_result.exceptions
        )

        presence_result = (
            self.line_presence_validator.validate_group(
                group.contract,
                group.purchase_orders,
                group.invoices,
            )
        )

        exceptions.extend(
            presence_result.exceptions
        )

        quantity_result = (
            self.quantity_validator.validate_group(
                group.contract,
                group.purchase_orders,
                group.invoices,
            )
        )

        exceptions.extend(
            quantity_result.exceptions
        )

        price_result = (
            self.price_validator.validate_group(
                group.contract,
                group.purchase_orders,
                group.invoices,
            )
        )

        exceptions.extend(
            price_result.exceptions
        )

        for exception in exceptions:
            self._attach_evidence(exception)

        return ValidationResult(
            status=(
                "EXCEPTION"
                if exceptions
                else "PASS"
            ),
            exceptions=exceptions,
        )

    def _attach_evidence(
        self,
        exception: ValidationException,
    ) -> None:
        if exception.source is None:
            return

        source = exception.source

        if not source.document_path:
            return

        if source.page_number is None:
            return

        if not source.polygon:
            return

        document_name = locator_stem(
            source.document_path
        )

        raw_name = (
            f"{document_name}_"
            f"{exception.item_code or exception.type}_"
            f"{exception.field or 'record'}_"
            f"whole_row.png"
        )

        output_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            raw_name,
        )

        evidence_result = (
            self.evidence_generator
            .generate_row_evidence_from_source(
                document_path=source.document_path,
                page_number=source.page_number,
                polygon=source.polygon,
                output_name=output_name,
            )
        )

        exception.evidence = [
            {
                "document_path": (
                    evidence_result[
                        "document_path"
                    ]
                ),
                "field": "whole_row",
                "page_number": (
                    evidence_result[
                        "page_number"
                    ]
                ),
                "snip_path": (
                    evidence_result[
                        "snip_path"
                    ]
                ),
            }
        ]
