from io import BytesIO

from app.storage.document_storage import DocumentStorage
from app.storage.factory import get_document_storage


def read_document_bytes(
    locator: str,
    storage: DocumentStorage | None = None,
) -> bytes:
    document_storage = storage or get_document_storage()
    return document_storage.read_bytes(locator)


def open_document_stream(
    locator: str,
    storage: DocumentStorage | None = None,
) -> BytesIO:
    return BytesIO(
        read_document_bytes(locator, storage=storage)
    )
