from typing import List

from app.storage.document_storage import (
    DocumentHandle,
    DocumentStorage,
)
from app.storage.document_types import DOCUMENT_TYPES


class FilteredDocumentStorage(DocumentStorage):
    """
    Wraps another DocumentStorage and restricts list_documents()
    to a caller-specified set of locators.

    read_bytes() and exists() delegate unchanged to the backing
    store so that any locator can still be read.
    """

    def __init__(
        self,
        backend: DocumentStorage,
        allowed_locators: dict[str, List[str]] | None = None,
    ):
        self._backend = backend
        self._allowed = allowed_locators or {}

    def list_documents(
        self, category: str
    ) -> List[DocumentHandle]:
        all_handles = self._backend.list_documents(category)
        allowed = self._allowed.get(category)
        if allowed is None:
            return all_handles
        allowed_set = set(allowed)
        return [
            h for h in all_handles
            if h.locator in allowed_set or h.filename in allowed_set
        ]

    def read_bytes(self, locator: str) -> bytes:
        return self._backend.read_bytes(locator)

    def exists(self, locator: str) -> bool:
        return self._backend.exists(locator)
