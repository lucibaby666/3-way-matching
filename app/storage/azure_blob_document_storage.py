import os
from typing import List

from app.storage.document_types import DOCUMENT_TYPES
from app.storage.document_storage import (
    DocumentHandle,
    DocumentStorage,
    build_document_handle,
    is_supported_document,
)
from app.storage.locator import (
    azure_locator,
    is_azure_locator,
    parse_azure_locator,
)


class AzureBlobDocumentStorage(DocumentStorage):
    """
    Reads documents from an Azure Blob container.

    Blob layout matches the local POC folders:

        contracts/
        purchase_orders/
        invoices/
    """

    def __init__(
        self,
        container_client,
        container_name: str,
        prefix: str = "",
    ):
        self._container_client = container_client
        self.container_name = container_name
        self.prefix = prefix.strip("/")

    @classmethod
    def from_env(cls) -> "AzureBlobDocumentStorage":
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        container_name = os.getenv("AZURE_BLOB_CONTAINER")

        if not container_name:
            raise ValueError(
                "AZURE_BLOB_CONTAINER is not configured."
            )

        prefix = os.getenv("AZURE_BLOB_PREFIX", "")
        connection_string = os.getenv(
            "AZURE_STORAGE_CONNECTION_STRING"
        )
        account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")

        if connection_string:
            service = BlobServiceClient.from_connection_string(
                connection_string
            )
        elif account_url:
            service = BlobServiceClient(
                account_url=account_url,
                credential=DefaultAzureCredential(),
            )
        else:
            raise ValueError(
                "Configure AZURE_STORAGE_CONNECTION_STRING "
                "or AZURE_STORAGE_ACCOUNT_URL."
            )

        return cls(
            container_client=service.get_container_client(
                container_name
            ),
            container_name=container_name,
            prefix=prefix,
        )

    def list_documents(
        self,
        category: str,
    ) -> List[DocumentHandle]:
        if category not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document category: {category}"
            )

        category_prefix = self._blob_prefix(category)
        handles: List[DocumentHandle] = []

        for blob in self._container_client.list_blobs(
            name_starts_with=category_prefix
        ):
            blob_name = blob.name

            if blob_name.endswith("/"):
                continue

            filename = blob_name.rsplit("/", 1)[-1]

            if not is_supported_document(filename):
                continue

            locator = azure_locator(
                self.container_name,
                blob_name,
            )

            handles.append(
                build_document_handle(
                    locator=locator,
                    document_type=DOCUMENT_TYPES[category],
                    file_size=int(getattr(blob, "size", 0) or 0),
                )
            )

        return sorted(handles, key=lambda handle: handle.filename)

    def read_bytes(self, locator: str) -> bytes:
        blob_name = self._blob_name_from_locator(locator)

        try:
            downloader = self._container_client.download_blob(
                blob_name
            )
        except Exception as exc:
            if exc.__class__.__name__ in {
                "ResourceNotFoundError",
                "AzureError",
            }:
                raise FileNotFoundError(
                    f"Document not found: {locator}"
                ) from exc
            raise

        payload = downloader.readall()

        if payload is None:
            raise FileNotFoundError(
                f"Document not found: {locator}"
            )

        return payload

    def exists(self, locator: str) -> bool:
        try:
            blob_name = self._blob_name_from_locator(locator)
        except ValueError:
            return False

        blob_client = getattr(
            self._container_client,
            "get_blob_client",
            None,
        )

        if blob_client is not None:
            try:
                return blob_client(blob_name).exists()
            except Exception:
                return False

        try:
            self.read_bytes(locator)
            return True
        except FileNotFoundError:
            return False

    def _blob_prefix(self, category: str) -> str:
        if self.prefix:
            return f"{self.prefix}/{category}/"

        return f"{category}/"

    def _blob_name_from_locator(self, locator: str) -> str:
        if is_azure_locator(locator):
            container, blob_name = parse_azure_locator(locator)

            if container != self.container_name:
                raise FileNotFoundError(
                    f"Document not found: {locator}"
                )

            return blob_name

        return locator.lstrip("/")
