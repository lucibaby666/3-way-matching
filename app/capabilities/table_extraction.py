from typing import Any, Dict, List

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

from app.env import get_env
from app.storage.document_io import open_document_stream
from app.storage.document_storage import DocumentStorage


load_dotenv()


class TableExtractor:
    """
    Reusable Azure Document Intelligence table extraction capability.

    This capability extracts table structure and source locations.
    It does not create canonical Contract, PO, or Invoice models.
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

    def extract_tables(self, document_path: str) -> List[Dict[str, Any]]:
        """
        Extract tables from a document using Azure Document Intelligence.

        Returns a lightweight application-level representation containing:
        - table index
        - row/column counts
        - cells
        - cell coordinates
        - page number
        - bounding polygon
        """

        document = open_document_stream(
            document_path,
            storage=self.storage,
        )

        poller = self.client.begin_analyze_document(
            "prebuilt-layout",
            body=document,
        )

        result = poller.result()

        tables: List[Dict[str, Any]] = []

        for table_index, table in enumerate(result.tables):

            cells: List[Dict[str, Any]] = []

            for cell in table.cells:

                bounding_regions = []

                if cell.bounding_regions:
                    for region in cell.bounding_regions:

                        bounding_regions.append(
                            {
                                "page_number": region.page_number,
                                "polygon": [
                                    {
                                        "x": region.polygon[i],
                                        "y": region.polygon[i + 1],
                                    }
                                    for i in range(0, len(region.polygon), 2)
                                ],
                            }
                        )

                cells.append(
                    {
                        "row_index": cell.row_index,
                        "column_index": cell.column_index,
                        "content": cell.content,
                        "bounding_regions": bounding_regions,
                    }
                )

            tables.append(
                {
                    "table_index": table_index,
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "cells": cells,
                }
            )

        return tables