from typing import Any, Dict, List, Optional

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

from app.env import get_env
from app.storage.document_io import open_document_stream
from app.storage.document_storage import DocumentStorage


load_dotenv()


class InvoiceExtractor:
    """
    Lightweight invoice extraction capability for the POC.

    This extracts invoice-level fields and line-item information
    while preserving source-location information where available.

    This is NOT the canonical Invoice domain model.
    """

    def __init__(
        self,
        storage: DocumentStorage | None = None,
    ):
        self.storage = storage

        endpoint = get_env("DOCUMENT_INTELLIGENCE_ENDPOINT")
        api_key = get_env("DOCUMENT_INTELLIGENCE_API_KEY")

        if not endpoint:
            raise ValueError(
                "document-intelligence-endpoint is not configured."
            )

        if not api_key:
            raise ValueError(
                "document-intelligence-api-key is not configured."
            )

        self.client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )

    def extract_invoice(self, document_path: str) -> Dict[str, Any]:
        """
        Extract invoice information using Azure Document Intelligence.

        Returns a lightweight application-level representation
        containing extracted values and source locations.
        """

        document = open_document_stream(
            document_path,
            storage=self.storage,
        )

        poller = self.client.begin_analyze_document(
            "prebuilt-invoice",
            body=document,
        )

        result = poller.result()

        if not result.documents:
            raise ValueError(
                f"No invoice document was detected: {document_path}"
            )

        document_result = result.documents[0]
        fields = document_result.fields

        line_items = self._extract_line_items(
            fields.get("Items")
        )

        if self._line_items_are_merged(line_items):
            line_items = (
                self._extract_line_items_from_tables(
                    result.tables
                )
            )

        return {
            "document_path": document_path,

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

            "line_items": line_items,
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

    @staticmethod
    def _line_items_are_merged(
        line_items: List[Dict[str, Any]],
    ) -> bool:
        """
        Detect rows merged by the prebuilt model, where
        several item codes were collapsed into a single
        line item value.
        """

        for item in line_items:

            value = (
                item.get("item_code", {}).get("value")
            )

            if isinstance(value, str) and "\n" in value:
                return True

        return False

    def _extract_line_items_from_tables(
        self,
        tables: Optional[List[Any]],
    ) -> List[Dict[str, Any]]:
        """
        Rebuild line items from document tables when the
        prebuilt invoice Items field merged table rows.

        Uses the same analysis result, so no additional
        extraction call is required.
        """

        if not tables:
            return []

        for table in tables:

            columns = self._table_columns(table)

            if "item_code" not in columns:
                continue

            return self._table_rows_to_line_items(
                table,
                columns,
            )

        return []

    @staticmethod
    def _normalize_header(
        content: Any,
    ) -> str:
        text = str(content or "").strip().lower()

        if "(" in text:
            text = text.split("(")[0].strip()

        return text

    def _table_columns(
        self,
        table: Any,
    ) -> Dict[str, int]:
        columns: Dict[str, int] = {}

        header_rules = [
            ("item_code", "item code"),
            ("description", "description"),
            ("unit_price", "unit price"),
            ("quantity", "qty"),
            ("quantity", "quantity"),
            ("amount", "amount"),
            ("unit", "unit"),
        ]

        for cell in table.cells:

            if cell.row_index != 0:
                continue

            normalized = self._normalize_header(
                cell.content
            )

            if not normalized:
                continue

            for name, token in header_rules:

                if name in columns:
                    continue

                if token in normalized:
                    columns[name] = cell.column_index
                    break

        return columns

    def _table_rows_to_line_items(
        self,
        table: Any,
        columns: Dict[str, int],
    ) -> List[Dict[str, Any]]:

        cells_by_position = {
            (cell.row_index, cell.column_index): cell
            for cell in table.cells
        }

        row_cells: Dict[int, List[Any]] = {}

        for cell in table.cells:
            row_cells.setdefault(
                cell.row_index,
                [],
            ).append(cell)

        line_items = []

        for row_index in sorted(row_cells):

            if row_index == 0:
                continue

            item_code_cell = (
                cells_by_position.get(
                    (
                        row_index,
                        columns["item_code"],
                    )
                )
            )

            if item_code_cell is None:
                continue

            if not (
                item_code_cell.content or ""
            ).strip():
                continue

            union_source = (
                self._row_union_region(
                    row_cells[row_index]
                )
            )

            line_item: Dict[str, Any] = {}

            for name in (
                "item_code",
                "description",
                "quantity",
                "unit",
                "unit_price",
                "amount",
            ):

                column_index = columns.get(name)

                cell = (
                    cells_by_position.get(
                        (
                            row_index,
                            column_index,
                        )
                    )
                    if column_index is not None
                    else None
                )

                source = (
                    union_source
                    if name == "quantity"
                    else self._cell_region(cell)
                )

                line_item[name] = {
                    "value": (
                        cell.content.strip()
                        if cell is not None
                        and cell.content
                        else None
                    ),
                    "source": source,
                }

            line_items.append(line_item)

        return line_items

    @staticmethod
    def _cell_region(
        cell: Optional[Any],
    ) -> List[Dict[str, Any]]:
        """
        Convert one table cell bounding region into
        our lightweight source-location representation.
        """

        if cell is None or not cell.bounding_regions:
            return []

        region = cell.bounding_regions[0]

        return [
            {
                "page_number": region.page_number,
                "polygon": [
                    {
                        "x": region.polygon[i],
                        "y": region.polygon[i + 1],
                    }
                    for i in range(
                        0,
                        len(region.polygon),
                        2,
                    )
                ],
            }
        ]

    def _row_union_region(
        self,
        row_cells: List[Any],
    ) -> List[Dict[str, Any]]:
        """
        Build one polygon covering an entire table row so
        whole-row evidence shows every column.
        """

        regions = [
            cell.bounding_regions[0]
            for cell in row_cells
            if cell.bounding_regions
        ]

        if not regions:
            return []

        page_numbers = {
            region.page_number
            for region in regions
        }

        if len(page_numbers) > 1:
            return self._cell_region(row_cells[0])

        points: List[Dict[str, float]] = []

        for region in regions:
            polygon = region.polygon

            points.extend(
                {
                    "x": polygon[i],
                    "y": polygon[i + 1],
                }
                for i in range(
                    0,
                    len(polygon),
                    2,
                )
            )

        min_x = min(p["x"] for p in points)
        max_x = max(p["x"] for p in points)
        min_y = min(p["y"] for p in points)
        max_y = max(p["y"] for p in points)

        return [
            {
                "page_number": (
                    regions[0].page_number
                ),
                "polygon": [
                    {"x": min_x, "y": min_y},
                    {"x": max_x, "y": min_y},
                    {"x": max_x, "y": max_y},
                    {"x": min_x, "y": max_y},
                ],
            }
        ]