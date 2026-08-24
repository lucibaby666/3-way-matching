from typing import Dict, List

from app.storage.document_storage import DocumentStorage
from app.storage.document_types import DOCUMENT_TYPES
from app.storage.factory import create_document_storage
from app.storage.local_document_storage import (
    LocalDocumentStorage,
)


class DocumentIntake:
    """
    Discovers documents from configured storage
    and produces basic intake metadata.

    This capability does not perform document extraction.
    Local directories and Azure Blob Storage are both
    supported through DocumentStorage.
    """

    def __init__(
        self,
        data_dir: str = "data",
        storage: DocumentStorage | None = None,
    ):
        self.storage = storage or LocalDocumentStorage(
            data_dir
        )

    @classmethod
    def from_env(cls) -> "DocumentIntake":
        return cls(storage=create_document_storage())

    def discover_documents(self) -> Dict[str, List[Dict[str, object]]]:
        """
        Discover supported documents and return intake metadata.
        """

        return {
            category: [
                handle.as_intake_dict()
                for handle in self.storage.list_documents(
                    category
                )
            ]
            for category in DOCUMENT_TYPES
        }

    def classify_document(self, document_category: str) -> str:
        """
        Classify a document based on the POC data-folder category.
        """

        if document_category not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document category: {document_category}"
            )

        return DOCUMENT_TYPES[document_category]
