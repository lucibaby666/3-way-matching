from pathlib import Path
from typing import List

from app.storage.document_types import DOCUMENT_TYPES
from app.storage.document_storage import (
    DocumentHandle,
    DocumentStorage,
    build_document_handle,
    is_supported_document,
)
from app.storage.locator import is_azure_locator


class LocalDocumentStorage(DocumentStorage):
    """
    Reads documents from a local data directory.

    Folder layout matches the POC:

        {data_dir}/contracts/
        {data_dir}/purchase_orders/
        {data_dir}/invoices/
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)

    def list_documents(
        self,
        category: str,
    ) -> List[DocumentHandle]:
        if category not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document category: {category}"
            )

        directory = self.data_dir / category

        if not directory.exists():
            return []

        handles: List[DocumentHandle] = []

        for file_path in sorted(directory.iterdir()):
            if not file_path.is_file():
                continue

            if not is_supported_document(file_path.name):
                continue

            locator = str(file_path)

            handles.append(
                build_document_handle(
                    locator=locator,
                    document_type=DOCUMENT_TYPES[category],
                    file_size=file_path.stat().st_size,
                )
            )

        return handles

    def read_bytes(self, locator: str) -> bytes:
        if is_azure_locator(locator):
            raise FileNotFoundError(
                f"Local storage cannot read Azure locator: {locator}"
            )

        path = Path(locator)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {locator}"
            )

        if not path.is_file():
            raise ValueError(
                f"Document path is not a file: {locator}"
            )

        return path.read_bytes()

    def exists(self, locator: str) -> bool:
        if is_azure_locator(locator):
            return False

        path = Path(locator)

        return path.exists() and path.is_file()
