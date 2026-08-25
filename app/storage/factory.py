from functools import lru_cache

from dotenv import load_dotenv

from app.env import get_env
from app.storage.azure_blob_document_storage import (
    AzureBlobDocumentStorage,
)
from app.storage.document_storage import DocumentStorage
from app.storage.local_document_storage import (
    LocalDocumentStorage,
)
from app.storage.locator import is_azure_locator


load_dotenv()


class RoutingDocumentStorage(DocumentStorage):
    """
    Lists from the configured backend and reads by locator scheme.

    Local paths always go to the filesystem. Azure locators go to
    Blob Storage when that backend is configured.
    """

    def __init__(
        self,
        primary: DocumentStorage,
        local: LocalDocumentStorage,
        azure: AzureBlobDocumentStorage | None = None,
    ):
        self._primary = primary
        self._local = local
        self._azure = azure
        self._cache: dict[str, bytes] = {}

    def list_documents(self, category: str):
        return self._primary.list_documents(category)

    def read_bytes(self, locator: str) -> bytes:
        if locator in self._cache:
            return self._cache[locator]

        if is_azure_locator(locator):
            if self._azure is None:
                raise FileNotFoundError(
                    "Azure Blob Storage is not configured "
                    f"for locator: {locator}"
                )

            payload = self._azure.read_bytes(locator)
        else:
            payload = self._local.read_bytes(locator)

        self._cache[locator] = payload
        return payload

    def exists(self, locator: str) -> bool:
        if is_azure_locator(locator):
            if self._azure is None:
                return False

            return self._azure.exists(locator)

        return self._local.exists(locator)


def create_document_storage() -> DocumentStorage:
    backend = get_env(
        "DOCUMENT_STORAGE",
        "local",
    ).strip().lower()

    data_dir = get_env("DOCUMENT_DATA_DIR", "data")
    local = LocalDocumentStorage(data_dir)

    if backend in {"azure", "blob", "azure_blob"}:
        azure = AzureBlobDocumentStorage.from_env()
        return RoutingDocumentStorage(
            primary=azure,
            local=local,
            azure=azure,
        )

    return RoutingDocumentStorage(
        primary=local,
        local=local,
        azure=None,
    )


@lru_cache(maxsize=1)
def get_document_storage() -> DocumentStorage:
    return create_document_storage()
