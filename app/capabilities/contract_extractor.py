import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv


load_dotenv()


class ContractExtractor:
    """
    Lightweight contract extraction capability for the POC.

    Extracts contract-level information, rules, and line items
    from Azure Document Intelligence layout analysis.

    This is NOT the canonical Contract domain model.
    """

    def __init__(self, storage: Any = None):
        self.storage = storage
        try:
            from secrets_manager import get_secret
        except ImportError:
            def get_secret(k, default=""):
                return os.getenv(k, default)

        use_local = get_secret("USE_LOCAL_EXTRACTOR", "false").strip().lower() in {"1", "true", "yes"}
        endpoint = get_secret("DOCUMENT_INTELLIGENCE_ENDPOINT")
        api_key = get_secret("DOCUMENT_INTELLIGENCE_API_KEY")


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

    def extract_contract(self, document_path: str, storage: Any = None) -> Dict[str, Any]:
        """
        Extract contract information using Azure Document Intelligence.
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

        paragraphs = self._get_paragraphs(result)

        return {
            "document_path": str(document_path),

            "contract_number": self._extract_contract_number(
                paragraphs
            ),

            "contract_date": self._extract_contract_date(
                paragraphs
            ),

            "buyer": self._extract_named_value(
                paragraphs,
                "Buyer",
            ),

            "supplier": self._extract_named_value(
                paragraphs,
                "Supplier",
            ),

            "contract_validity": self._extract_validity(
                paragraphs
            ),

            "payment_terms": self._extract_payment_terms(
                paragraphs
            ),

            "quantity_tolerance": self._extract_quantity_tolerance(
                paragraphs
            ),

            "price_tolerance": self._extract_price_tolerance(
                paragraphs
            ),

            "invoice_rule": self._extract_invoice_rule(
                paragraphs
            ),

            "line_items": self._extract_line_items(
                result
            ),
        }

    @staticmethod
    def _get_paragraphs(
        result: Any,
    ) -> List[Any]:
        """
        Return paragraphs from Azure Document Intelligence.
        """

        return result.paragraphs or []

    @staticmethod
    def _find_paragraph(
        paragraphs: List[Any],
        keyword: str,
    ) -> Optional[Any]:
        """
        Find the first paragraph containing a keyword.
        """

        keyword_lower = keyword.lower()

        for paragraph in paragraphs:
            if keyword_lower in paragraph.content.lower():
                return paragraph

        return None

    @classmethod
    def _extract_contract_number(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        paragraph = cls._find_paragraph(
            paragraphs,
            "Contract Number:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Contract Number:\s*([A-Za-z0-9\-]+)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1),
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_contract_date(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        paragraph = cls._find_paragraph(
            paragraphs,
            "Contract Date:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Contract Date:\s*([0-9]{2}\s+[A-Za-z]+\s+[0-9]{4})",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1),
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_named_value(
        cls,
        paragraphs: List[Any],
        field_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract fields such as Buyer and Supplier.

        The current contract has Buyer and Supplier in the same
        paragraph, so the paragraph itself is retained as evidence.
        """

        paragraph = cls._find_paragraph(
            paragraphs,
            f"{field_name}:",
        )

        if paragraph is None:
            return None

        match = re.search(
            rf"{re.escape(field_name)}:\s*(.*?)(?=\s+(?:Buyer|Supplier):|$)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_validity(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        paragraph = cls._find_paragraph(
            paragraphs,
            "Contract Validity:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Contract Validity:\s*(.+)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": cls._get_paragraph_source(
                paragraph
            ),
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
            r"Payment Terms:\s*(.+)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_quantity_tolerance(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        paragraph = cls._find_paragraph(
            paragraphs,
            "Quantity Tolerance:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Quantity Tolerance:\s*([+\-]?\d+(?:\.\d+)?)%",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": f"{match.group(1)}%",
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_price_tolerance(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        paragraph = cls._find_paragraph(
            paragraphs,
            "Price Tolerance:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Price Tolerance:\s*([+\-±]?\d+(?:\.\d+)?)%",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": f"{match.group(1)}%",
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @classmethod
    def _extract_invoice_rule(
        cls,
        paragraphs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        paragraph = cls._find_paragraph(
            paragraphs,
            "Invoice Rule:",
        )

        if paragraph is None:
            return None

        match = re.search(
            r"Invoice Rule:\s*(.+)",
            paragraph.content,
            re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "value": match.group(1).strip(),
            "source": cls._get_paragraph_source(
                paragraph
            ),
        }

    @staticmethod
    def _get_paragraph_source(
        paragraph: Any,
    ) -> List[Dict[str, Any]]:
        """
        Convert Azure paragraph bounding regions into our
        lightweight source-location representation.
        """

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

    @staticmethod
    def _extract_line_items(
        result: Any,
    ) -> List[Dict[str, Any]]:
        """
        Extract contract line items from the first detected table.
        """

        if not result.tables:
            return []

        table = result.tables[0]

        cells = {}

        for cell in table.cells:
            cells[
                (cell.row_index, cell.column_index)
            ] = cell

        line_items = []

        for row_index in range(1, table.row_count):

            item_code = cells.get((row_index, 0))
            description = cells.get((row_index, 1))
            quantity = cells.get((row_index, 2))
            unit = cells.get((row_index, 3))
            unit_price = cells.get((row_index, 4))
            tax = cells.get((row_index, 5))

            if not item_code:
                continue

            line_items.append(
                {
                    "item_code": ContractExtractor._field_with_source(
                        item_code
                    ),
                    "description": ContractExtractor._field_with_source(
                        description
                    ),
                    "quantity": ContractExtractor._field_with_source(
                        quantity
                    ),
                    "unit": ContractExtractor._field_with_source(
                        unit
                    ),
                    "unit_price": ContractExtractor._field_with_source(
                        unit_price
                    ),
                    "tax": ContractExtractor._field_with_source(
                        tax
                    ),
                }
            )

        return line_items

    @staticmethod
    def _field_with_source(
        cell: Any,
    ) -> Dict[str, Any]:
        """
        Convert an Azure table cell into our lightweight
        value + source representation.
        """

        return {
            "value": cell.content,
            "source": ContractExtractor._get_source_location(
                cell
            ),
        }

    @staticmethod
    def _get_source_location(
        cell: Any,
    ) -> List[Dict[str, Any]]:
        """
        Convert Azure cell bounding regions into our
        lightweight source-location representation.
        """

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