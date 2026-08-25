from typing import Dict, List

from app.storage.document_storage import (
    DocumentHandle,
    DocumentStorage,
    build_document_handle,
    is_supported_document,
)
from app.storage.document_types import DOCUMENT_TYPES
from app.storage.locator import locator_filename


class UploadSessionDocumentStorage(DocumentStorage):
    """
    Stores uploaded documents in a shared backend (e.g. Azure
    Blob Storage) using the canonical folder layout:

        contracts/
        purchase_orders/
        invoices/

    Listing is scoped to the handles uploaded during this
    session so each match run only sees its own document set,
    even though the backend container may hold documents from
    many sessions.
    """

    def __init__(self, backend: DocumentStorage):
        self._backend = backend
        self._handles: Dict[str, List[DocumentHandle]] = {
            category: []
            for category in DOCUMENT_TYPES
        }

    def add_document(
        self,
        category: str,
        locator: str,
        payload: bytes,
    ) -> DocumentHandle:
        if category not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document category: {category}"
            )

        filename = locator_filename(locator)

        if not is_supported_document(filename):
            raise ValueError(
                f"Unsupported document: {locator}"
            )

        blob_name = f"{category}/{filename}"
        self._backend.write_bytes(blob_name, payload)

        handle = build_document_handle(
            locator=self._session_locator(blob_name),
            document_type=DOCUMENT_TYPES[category],
            file_size=len(payload),
        )
        self._handles[category].append(handle)

        return handle

    def list_documents(
        self,
        category: str,
    ) -> List[DocumentHandle]:
        if category not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document category: {category}"
            )

        return sorted(
            self._handles[category],
            key=lambda handle: handle.filename,
        )

    def read_bytes(self, locator: str) -> bytes:
        return self._backend.read_bytes(locator)

    def exists(self, locator: str) -> bool:
        return self._backend.exists(locator)

    def _session_locator(self, blob_name: str) -> str:
        to_azure_locator = getattr(
            self._backend,
            "azure_locator_for",
            None,
        )

        if to_azure_locator is not None:
            return to_azure_locator(blob_name)

        return blob_name
