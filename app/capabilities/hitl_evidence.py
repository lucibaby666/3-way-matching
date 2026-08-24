from typing import Any

from app.capabilities.evidence_generator import (
    EvidenceGenerator,
)
from app.storage.locator import locator_stem


class HITLEvidenceService:
    """
    POC service responsible for generating visual evidence
    for a matched line item.

    It uses the raw extracted document representation,
    where field-level Azure Document Intelligence source
    polygons are still available.

    This service does not perform matching or validation.
    """

    def __init__(
        self,
        evidence_generator: EvidenceGenerator | None = None,
        output_dir: str = "outputs/evidence",
    ):
        self.evidence_generator = (
            evidence_generator
            or EvidenceGenerator(
                output_dir=output_dir
            )
        )

    def generate_row_evidence(
        self,
        document_path: str,
        line_item: dict[str, Any],
        item_code: str,
    ) -> dict[str, Any]:
        """
        Generate whole-row evidence for one line item.
        """

        if not document_path:
            raise ValueError(
                "document_path cannot be empty."
            )

        if not line_item:
            raise ValueError(
                "line_item cannot be empty."
            )

        if not item_code:
            raise ValueError(
                "item_code cannot be empty."
            )

        output_name = (
            f"{locator_stem(document_path)}"
            f"_{item_code}"
            f"_whole_row.png"
        )

        return (
            self.evidence_generator
            .generate_row_evidence(
                document_path=document_path,
                line_item=line_item,
                output_name=output_name,
            )
        )