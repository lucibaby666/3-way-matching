from pathlib import Path
from typing import Any, Dict, List

from app.capabilities.document_snip import DocumentSnip
from app.storage.locator import locator_stem


class EvidenceGenerator:
    """
    Generates visual evidence for validation exceptions.

    Supported evidence modes:

    1. Field-level evidence
       generate_evidence()

    2. Whole-row evidence from raw extractor data
       generate_row_evidence()

    3. Whole-row evidence from a canonical SourceReference
       generate_row_evidence_from_source()

    The matching engine can use the third method for the
    current POC because the canonical LineItem currently
    retains a single source reference.
    """

    def __init__(
        self,
        document_snip: DocumentSnip | None = None,
        output_dir: str = "outputs/evidence",
    ):
        self.document_snip = (
            document_snip or DocumentSnip()
        )

        self.output_dir = Path(output_dir)

    # ============================================================
    # FIELD-LEVEL EVIDENCE
    # ============================================================

    def generate_evidence(
        self,
        exception_type: str,
        evidence_references: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate field-level evidence snippets.
        """

        if not exception_type:
            raise ValueError(
                "exception_type cannot be empty"
            )

        if not evidence_references:
            raise ValueError(
                "evidence_references cannot be empty"
            )

        generated_evidence = []

        for index, reference in enumerate(
            evidence_references
        ):
            document_path = reference.get(
                "document_path"
            )

            field = reference.get(
                "field"
            )

            page_number = reference.get(
                "page_number"
            )

            polygon = reference.get(
                "polygon"
            )

            if not document_path:
                raise ValueError(
                    "Evidence reference requires "
                    "document_path"
                )

            if not field:
                raise ValueError(
                    "Evidence reference requires field"
                )

            if page_number is None:
                raise ValueError(
                    "Evidence reference requires "
                    "page_number"
                )

            if not polygon:
                raise ValueError(
                    "Evidence reference requires polygon"
                )

            document_name = locator_stem(
                document_path
            )

            output_path = (
                self.output_dir
                / f"{document_name}_{field}_{index}.png"
            )

            snip_path = (
                self.document_snip.create_snip(
                    document_path=document_path,
                    page_number=page_number,
                    polygon=polygon,
                    output_path=str(
                        output_path
                    ),
                )
            )

            generated_evidence.append(
                {
                    "document_path": document_path,
                    "field": field,
                    "page_number": page_number,
                    "snip_path": snip_path,
                }
            )

        return {
            "exception_type": exception_type,
            "evidence": generated_evidence,
        }

    # ============================================================
    # WHOLE ROW FROM RAW EXTRACTOR DATA
    # ============================================================

    def generate_row_evidence(
        self,
        document_path: str,
        line_item: Dict[str, Any],
        output_name: str,
    ) -> Dict[str, Any]:
        """
        Generate one visual evidence snapshot containing
        the complete line-item / row.

        Expected input is the raw extractor representation:

            {
                "item_code": {
                    "value": "...",
                    "source": [
                        {
                            "page_number": 1,
                            "polygon": [...]
                        }
                    ]
                },
                "quantity": {...},
                "unit_price": {...},
                "amount": {...}
            }

        All available field polygons are combined into one
        bounding rectangle.
        """

        if not document_path:
            raise ValueError(
                "document_path cannot be empty"
            )

        if not line_item:
            raise ValueError(
                "line_item cannot be empty"
            )

        if not output_name:
            raise ValueError(
                "output_name cannot be empty"
            )

        row_polygon = self._build_row_polygon(
            line_item
        )

        if not row_polygon:
            raise ValueError(
                "Unable to build row polygon "
                "because no field coordinates exist."
            )

        page_number = (
            self._get_row_page_number(
                line_item
            )
        )

        if page_number is None:
            raise ValueError(
                "Unable to determine row page number."
            )

        output_path = (
            self.output_dir / output_name
        )

        snip_path = (
            self.document_snip.create_snip(
                document_path=document_path,
                page_number=page_number,
                polygon=row_polygon,
                output_path=str(
                    output_path
                ),
            )
        )

        return {
            "document_path": document_path,
            "page_number": page_number,
            "field": "whole_row",
            "polygon": row_polygon,
            "snip_path": snip_path,
        }

    # ============================================================
    # WHOLE ROW FROM CANONICAL SOURCE
    # ============================================================

    def generate_row_evidence_from_source(
        self,
        document_path: str,
        page_number: int,
        polygon: List[Dict[str, float]],
        output_name: str,
        horizontal_padding: float = 3.0,
        vertical_padding: float = 0.15,
    ) -> Dict[str, Any]:
        """
        Generate a whole-row evidence snippet using the
        exception source polygon as the row anchor.

        POC approach:

        The canonical LineItem currently retains only one
        SourceReference rather than every field-level polygon.

        Therefore, the source polygon is expanded horizontally
        to capture the complete row.

        Coordinates are expected to be in inches, consistent
        with the current DocumentSnip implementation.
        """

        if not document_path:
            raise ValueError(
                "document_path cannot be empty"
            )

        if page_number is None:
            raise ValueError(
                "page_number cannot be None"
            )

        if not polygon:
            raise ValueError(
                "polygon cannot be empty"
            )

        if horizontal_padding < 0:
            raise ValueError(
                "horizontal_padding cannot be negative"
            )

        if vertical_padding < 0:
            raise ValueError(
                "vertical_padding cannot be negative"
            )

        min_x = min(
            point["x"]
            for point in polygon
        )

        max_x = max(
            point["x"]
            for point in polygon
        )

        min_y = min(
            point["y"]
            for point in polygon
        )

        max_y = max(
            point["y"]
            for point in polygon
        )

        row_polygon = [
            {
                "x": max(
                    0.0,
                    min_x - horizontal_padding,
                ),
                "y": max(
                    0.0,
                    min_y - vertical_padding,
                ),
            },
            {
                "x": max_x + horizontal_padding,
                "y": max(
                    0.0,
                    min_y - vertical_padding,
                ),
            },
            {
                "x": max_x + horizontal_padding,
                "y": max_y + vertical_padding,
            },
            {
                "x": max(
                    0.0,
                    min_x - horizontal_padding,
                ),
                "y": max_y + vertical_padding,
            },
        ]

        output_path = (
            self.output_dir / output_name
        )

        snip_path = (
            self.document_snip.create_snip(
                document_path=document_path,
                page_number=page_number,
                polygon=row_polygon,
                output_path=str(
                    output_path
                ),
            )
        )

        return {
            "document_path": document_path,
            "field": "whole_row",
            "page_number": page_number,
            "polygon": row_polygon,
            "snip_path": snip_path,
        }

    # ============================================================
    # INTERNAL: BUILD ROW POLYGON
    # ============================================================

    @staticmethod
    def _build_row_polygon(
        line_item: Dict[str, Any],
    ) -> List[Dict[str, float]]:
        """
        Combine all available field polygons from one
        raw extracted line item into one bounding rectangle.
        """

        fields = (
            "item_code",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "tax",
            "amount",
        )

        points: List[
            Dict[str, float]
        ] = []

        for field_name in fields:
            field = line_item.get(
                field_name
            )

            if not field:
                continue

            locations = field.get(
                "source",
                [],
            )

            for location in locations:
                polygon = location.get(
                    "polygon",
                    [],
                )

                for point in polygon:
                    x = point.get("x")
                    y = point.get("y")

                    if x is None or y is None:
                        continue

                    points.append(
                        {
                            "x": float(x),
                            "y": float(y),
                        }
                    )

        if not points:
            return []

        min_x = min(
            point["x"]
            for point in points
        )

        max_x = max(
            point["x"]
            for point in points
        )

        min_y = min(
            point["y"]
            for point in points
        )

        max_y = max(
            point["y"]
            for point in points
        )

        return [
            {
                "x": min_x,
                "y": min_y,
            },
            {
                "x": max_x,
                "y": min_y,
            },
            {
                "x": max_x,
                "y": max_y,
            },
            {
                "x": min_x,
                "y": max_y,
            },
        ]

    # ============================================================
    # INTERNAL: GET ROW PAGE
    # ============================================================

    @staticmethod
    def _get_row_page_number(
        line_item: Dict[str, Any],
    ) -> int | None:
        """
        Determine the page number for the row.

        For the POC, the first available field source
        determines the page.
        """

        fields = (
            "item_code",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "tax",
            "amount",
        )

        for field_name in fields:
            field = line_item.get(
                field_name
            )

            if not field:
                continue

            locations = field.get(
                "source",
                [],
            )

            if not locations:
                continue

            page_number = locations[0].get(
                "page_number"
            )

            if page_number is not None:
                return page_number

        return None