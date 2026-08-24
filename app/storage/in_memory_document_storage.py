from typing import Dict, List

from app.storage.document_types import DOCUMENT_TYPES
from app.storage.document_storage import (
    DocumentHandle,
    DocumentStorage,
    build_document_handle,
    is_supported_document,
)
from app.storage.locator import locator_filename


class InMemoryDocumentStorage(DocumentStorage):
    """
    Test double that stores document bytes in memory.
    """

    def __init__(self):
        self._blobs: Dict[str, bytes] = {}
        self._categories: Dict[str, List[str]] = {
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

        if not is_supported_document(locator_filename(locator)):
            raise ValueError(
                f"Unsupported document: {locator}"
            )

        self._blobs[locator] = payload

        if locator not in self._categories[category]:
            self._categories[category].append(locator)

        return build_document_handle(
            locator=locator,
            document_type=DOCUMENT_TYPES[category],
            file_size=len(payload),
        )

    def list_documents(
        self,
        category: str,
    ) -> List[DocumentHandle]:
        if category not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document category: {category}"
            )

        handles = [
            build_document_handle(
                locator=locator,
                document_type=DOCUMENT_TYPES[category],
                file_size=len(self._blobs[locator]),
            )
            for locator in self._categories[category]
            if locator in self._blobs
        ]

        return sorted(handles, key=lambda handle: handle.filename)

    def read_bytes(self, locator: str) -> bytes:
        if locator not in self._blobs:
            raise FileNotFoundError(
                f"Document not found: {locator}"
            )

        return self._blobs[locator]

    def exists(self, locator: str) -> bool:
        return locator in self._blobs
