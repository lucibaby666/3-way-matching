import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv


load_dotenv()


class PurchaseOrderExtractor:
    """
    Lightweight Purchase Order extraction capability.

    Uses Azure Document Intelligence layout analysis and
    preserves source locations for extracted values.

    This is NOT the canonical PurchaseOrder model.
    """

    def __init__(self, storage: Any = None):
        self.storage = storage
        use_local = os.getenv("USE_LOCAL_EXTRACTOR", "false").strip().lower() in {"1", "true", "yes"}
        endpoint = os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT")
        api_key = os.getenv("DOCUMENT_INTELLIGENCE_API_KEY")


        if not use_local and endpoint and api_key:
            try:
                self.client = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=AzureKeyCredential(api_key),
                    retry_total=0,
                    retry_backoff_factor=0,
                    retry_backoff_max=0,
                )
            except Exception as e:
                logger.warning(f"Could not initialize Azure DI Client: {e}")
                self.client = None
        else:
            self.client = None

    def extract_purchase_order(
        self,
        document_path: str,
        storage: Any = None,
    ) -> Dict[str, Any]:
        """
        Extract Purchase Order information.
        """
        effective_storage = storage or self.storage
        if effective_storage and effective_storage.exists(document_path):
            doc_bytes = effective_storage.read_bytes(document_path)
        else:
            path = Path(document_path)
            if path.exists() and path.is_file():
                doc_bytes = path.read_bytes()
            elif (Path("data") / document_path).exists() and (Path("data") / document_path).is_file():
                doc_bytes = (Path("data") / document_path).read_bytes()
            else:
                try:
                    from app.storage.document_io import read_document_bytes
                    doc_bytes = read_document_bytes(document_path, storage=effective_storage)
                except Exception:
                    raise FileNotFoundError(
                        f"Document not found: {document_path}"
                    )

        result = None
        if self.client:
            try:
                poller = self.client.begin_analyze_document(
                    "prebuilt-layout",
                    body=doc_bytes,
                    polling_interval=1,
                )
                result = poller.result()
            except Exception as err:
                logger.warning(
                    f"Azure Document Intelligence error ({err}). Switching to fast local extractor."
                )
                self.client = None  # Circuit breaker

        if result is None:
            from app.capabilities.local_pdf_extractor import parse_pdf_layout_locally
            result = parse_pdf_layout_locally(doc_bytes)

        paragraphs = result.paragraphs or []

        return {
            "document_path": str(document_path),

            "po_number": self._extract_named_value(
                paragraphs,
                "PO Number",
            ),

            "po_date": self._extract_named_value(
                paragraphs,
                "PO Date",
            ),

            "contract_reference": self._extract_named_value(
                paragraphs,
                "Contract Reference",
            ),

            "buyer": self._extract_named_value(
                paragraphs,
                "Buyer",
            ),

            "supplier": self._extract_named_value(
                paragraphs,
                "Supplier",
            ),

            "subtotal": self._extract_subtotal(
                paragraphs
            ),

            "gst": self._extract_gst(
                paragraphs
            ),

            "payment_terms": self._extract_payment_terms(
                paragraphs
            ),

            "delivery_terms": self._extract_delivery_terms(
                paragraphs
            ),

            "line_items": self._extract_line_items(
                result
            ),
        }

    @staticmethod
    def _extract_named_value(
        paragraphs: List[Any],
        field_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract a field from the PO header paragraph.

        The current PO contains all header fields in one paragraph.
        """

        paragraph = None

        for candidate in paragraphs:

            if field_name.lower() in candidate.content.lower():
                paragraph = candidate
                break

        if paragraph is None:
            return None

        # Stop at the next known header field.
        known_fields = [
            "PO Number",
            "PO Date",
            "Contract Reference",
            "Buyer",
            "Supplier",
        ]

        stop_pattern = "|".join(
            re.escape(field)
            for field in known_fields
            if field.lower() != field_name.lower()
        )

        match = re.search(
            rf"{re.escape(field_name)}:\s*(.*?)(?=\s+(?:{stop_pattern}):|$)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": PurchaseOrderExtractor._get_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_subtotal(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:

        paragraph = cls._find_paragraph(
            paragraphs,
            "Subtotal:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Subtotal:\s*INR\s*([\d,]+(?:\.\d+)?)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1),
            "source": cls._get_source(paragraph),
        }

    @classmethod
    def _extract_gst(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:

        paragraph = cls._find_paragraph(
            paragraphs,
            "GST:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"GST:\s*([\d.]+%)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1),
            "source": cls._get_source(paragraph),
        }

    @classmethod
    def _extract_payment_terms(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:

        paragraph = cls._find_paragraph(
            paragraphs,
            "Payment Terms:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Payment Terms:\s*(.*?)(?=\s+Delivery:|$)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": cls._get_source(paragraph),
        }

    @classmethod
    def _extract_delivery_terms(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:

        paragraph = cls._find_paragraph(
            paragraphs,
            "Delivery:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Delivery:\s*(.+)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": cls._get_source(paragraph),
        }

    @staticmethod
    def _find_paragraph(
        paragraphs: List[Any],
        keyword: str,
    ) -> Optional[Any]:

        for paragraph in paragraphs:

            if keyword.lower() in paragraph.content.lower():
                return paragraph

        return None

    @staticmethod
    def _get_source(
        paragraph: Any,
    ) -> List[Dict[str, Any]]:

        if not paragraph.bounding_regions:
            return []

        locations = []

        for region in paragraph.bounding_regions:

            polygon = region.polygon

            locations.append(
                {
                    "page_number": region.page_number,
                    "polygon": [
                        {
                            "x": polygon[i],
                            "y": polygon[i + 1],
                        }
                        for i in range(
                            0,
                            len(polygon),
                            2,
                        )
                    ],
                }
            )

        return locations

    @classmethod
    def _extract_line_items(
        cls,
        result: Any,
    ) -> List[Dict[str, Any]]:

        if not result.tables:
            return []

        table = result.tables[0]

        cells = {}

        for cell in table.cells:

            cells[
                (cell.row_index, cell.column_index)
            ] = cell

        line_items = []

        # Row 0 = header.
        for row_index in range(
            1,
            table.row_count,
        ):

            item_code = cells.get(
                (row_index, 1)
            )

            description = cells.get(
                (row_index, 2)
            )

            quantity = cells.get(
                (row_index, 3)
            )

            unit = cells.get(
                (row_index, 4)
            )

            unit_price = cells.get(
                (row_index, 5)
            )

            amount = cells.get(
                (row_index, 6)
            )

            if not item_code:
                continue

            line_items.append(
                {
                    "item_code": cls._field(
                        item_code
                    ),
                    "description": cls._field(
                        description
                    ),
                    "quantity": cls._field(
                        quantity
                    ),
                    "unit": cls._field(
                        unit
                    ),
                    "unit_price": cls._field(
                        unit_price
                    ),
                    "amount": cls._field(
                        amount
                    ),
                }
            )

        return line_items

    @classmethod
    def _field(
        cls,
        cell: Any,
    ) -> Dict[str, Any]:

        return {
            "value": cell.content,
            "source": cls._cell_source(cell),
        }

    @staticmethod
    def _cell_source(
        cell: Any,
    ) -> List[Dict[str, Any]]:

        if not cell.bounding_regions:
            return []

        locations = []

        for region in cell.bounding_regions:

            polygon = region.polygon

            locations.append(
                {
                    "page_number": region.page_number,
                    "polygon": [
                        {
                            "x": polygon[i],
                            "y": polygon[i + 1],
                        }
                        for i in range(
                            0,
                            len(polygon),
                            2,
                        )
                    ],
                }
            )

        return locations