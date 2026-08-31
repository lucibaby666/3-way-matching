import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv


load_dotenv()


class InvoiceExtractor:
    """
    Lightweight invoice extraction capability for the POC.

    This extracts invoice-level fields and line-item information
    while preserving source-location information where available.

    This is NOT the canonical Invoice domain model.
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

    def extract_invoice(self, document_path: str, storage: Any = None) -> Dict[str, Any]:
        """
        Extract invoice information using Azure Document Intelligence.

        Returns a lightweight application-level representation
        containing extracted values and source locations.
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
                    "prebuilt-invoice",
                    body=doc_bytes,
                    polling_interval=1,
                )
                result = poller.result()
            except Exception as err:
                logger.warning(
                    f"Azure Document Intelligence error ({err}). Switching to fast local extractor."
                )
                self.client = None  # Circuit breaker

        if result is None or not getattr(result, "documents", None):
            from app.capabilities.local_pdf_extractor import extract_invoice_locally
            return extract_invoice_locally(doc_bytes, document_path)

        document_result = result.documents[0]
        fields = document_result.fields

        return {
            "document_path": str(document_path),

            "invoice_number": self._get_field_with_source(
                fields,
                "InvoiceId",
            ),

            "purchase_order": self._get_field_with_source(
                fields,
                "PurchaseOrder",
            ),

            "invoice_date": self._get_field_with_source(
                fields,
                "InvoiceDate",
            ),

            "due_date": self._get_field_with_source(
                fields,
                "DueDate",
            ),

            "vendor_name": self._get_field_with_source(
                fields,
                "VendorName",
            ),

            "customer_name": self._get_field_with_source(
                fields,
                "CustomerName",
            ),

            "subtotal": self._get_field_with_source(
                fields,
                "SubTotal",
            ),

            "total_tax": self._get_field_with_source(
                fields,
                "TotalTax",
            ),

            "invoice_total": self._get_field_with_source(
                fields,
                "InvoiceTotal",
            ),

            "line_items": self._extract_line_items(
                fields.get("Items")
            ),
        }

    @staticmethod
    def _get_field_value(
        fields: Dict[str, Any],
        field_name: str,
    ) -> Optional[Any]:
        """
        Safely retrieve a typed field value from Azure
        Document Intelligence.
        """

        field = fields.get(field_name)

        if field is None:
            return None

        field_type = str(field.type)

        if field_type == "string":
            return field.value_string

        if field_type == "number":
            return field.value_number

        if field_type == "integer":
            return field.value_integer

        if field_type == "date":
            return field.value_date

        if field_type == "time":
            return field.value_time

        if field_type == "currency":
            return field.value_currency

        if field_type == "boolean":
            return field.value_boolean

        if field_type == "object":
            return field.value_object

        if field_type == "array":
            return field.value_array

        return field.content

    @staticmethod
    def _get_source_location(
        field: Optional[Any],
    ) -> List[Dict[str, Any]]:
        """
        Convert Azure Document Intelligence bounding regions
        into our lightweight source-location representation.
        """

        if field is None or not field.bounding_regions:
            return []

        locations = []

        for region in field.bounding_regions:
            polygon = region.polygon

            locations.append(
                {
                    "page_number": region.page_number,
                    "polygon": [
                        {
                            "x": polygon[i],
                            "y": polygon[i + 1],
                        }
                        for i in range(0, len(polygon), 2)
                    ],
                }
            )

        return locations

    @classmethod
    def _get_field_with_source(
        cls,
        fields: Dict[str, Any],
        field_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return an extracted value together with its source location.
        """

        field = fields.get(field_name)

        if field is None:
            return None

        return {
            "value": cls._get_field_value(
                fields,
                field_name,
            ),
            "source": cls._get_source_location(
                field
            ),
        }

    def _extract_line_items(
    self,
    items_field: Optional[Any],
) -> List[Dict[str, Any]]:
        """
        Extract invoice line items and preserve source locations
        for individual fields.
        """

        if items_field is None:
            return []

        items = items_field.value_array

        if not items:
            return []

        line_items = []

        for item in items:

            item_fields = item.value_object

            if not item_fields:
                continue

            # Azure Document Intelligence may expose the product/item
            # identifier as ProductCode or ItemCode depending on the
            # invoice schema.
            item_code = (
                item_fields.get("ProductCode")
                or item_fields.get("ItemCode")
            )

            description = item_fields.get("Description")
            quantity = item_fields.get("Quantity")
            unit_price = item_fields.get("UnitPrice")
            amount = item_fields.get("Amount")

            line_items.append(
                {
                    "item_code": {
                        "value": (
                            self._get_field_value(
                                item_fields,
                                "ProductCode",
                            )
                            if item_fields.get("ProductCode")
                            else self._get_field_value(
                                item_fields,
                                "ItemCode",
                            )
                        ),
                        "source": self._get_source_location(
                            item_code
                        ),
                    },

                    "description": {
                        "value": self._get_field_value(
                            item_fields,
                            "Description",
                        ),
                        "source": self._get_source_location(
                            description
                        ),
                    },

                    "quantity": {
                        "value": self._get_field_value(
                            item_fields,
                            "Quantity",
                        ),
                        "source": self._get_source_location(
                            quantity
                        ),
                    },

                    "unit_price": {
                        "value": self._get_field_value(
                            item_fields,
                            "UnitPrice",
                        ),
                        "source": self._get_source_location(
                            unit_price
                        ),
                    },

                    "amount": {
                        "value": self._get_field_value(
                            item_fields,
                            "Amount",
                        ),
                        "source": self._get_source_location(
                            amount
                        ),
                    },
                }
            )

        return line_items