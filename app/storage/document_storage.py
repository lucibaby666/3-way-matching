from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List
from uuid import NAMESPACE_URL, uuid5

from app.storage.document_types import (
    DOCUMENT_TYPES,
    SUPPORTED_EXTENSIONS,
)
from app.storage.locator import locator_extension, locator_filename


@dataclass(frozen=True)
class DocumentHandle:
    document_id: str
    filename: str
    locator: str
    document_type: str
    file_extension: str
    file_size: int

    def as_intake_dict(self) -> Dict[str, object]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "path": self.locator,
            "document_type": self.document_type,
            "file_extension": self.file_extension,
            "file_size": self.file_size,
        }


def build_document_handle(
    locator: str,
    document_type: str,
    file_size: int,
) -> DocumentHandle:
    filename = locator_filename(locator)
    extension = locator_extension(locator)

    return DocumentHandle(
        document_id=str(
            uuid5(NAMESPACE_URL, locator)
        ),
        filename=filename,
        locator=locator,
        document_type=document_type,
        file_extension=extension,
        file_size=file_size,
    )


class DocumentStorage(ABC):
    """
    Abstract document store for intake, extraction, and evidence.

    Local filesystem and Azure Blob Storage are interchangeable
    implementations of this interface.
    """

    @abstractmethod
    def list_documents(
        self,
        category: str,
    ) -> List[DocumentHandle]:
        raise NotImplementedError

    @abstractmethod
    def read_bytes(self, locator: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def exists(self, locator: str) -> bool:
        raise NotImplementedError

    def list_all_documents(
        self,
    ) -> Dict[str, List[DocumentHandle]]:
        return {
            category: self.list_documents(category)
            for category in DOCUMENT_TYPES
        }


def is_supported_document(filename: str) -> bool:
    return locator_extension(filename) in SUPPORTED_EXTENSIONS
