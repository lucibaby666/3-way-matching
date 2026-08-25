from app.storage.upload_session_document_storage import (
    UploadSessionDocumentStorage,
)


class FakeAzureBackend:
    def __init__(self):
        self.blobs = {}

    def write_bytes(self, blob_name, payload):
        self.blobs[blob_name] = payload

    def read_bytes(self, locator):
        blob_name = (
            locator.removeprefix("azure://docs/")
        )

        if blob_name not in self.blobs:
            raise FileNotFoundError(
                f"Document not found: {locator}"
            )

        return self.blobs[blob_name]

    def exists(self, locator):
        return (
            locator.removeprefix("azure://docs/")
            in self.blobs
        )

    def azure_locator_for(self, blob_name):
        return f"azure://docs/{blob_name}"


def _pdf_payload():
    return b"%PDF-1.4 fake"


def test_add_document_uploads_to_category_folder():
    backend = FakeAzureBackend()
    storage = UploadSessionDocumentStorage(backend=backend)

    handle = storage.add_document(
        category="invoices",
        locator="invoices/invoice_A.pdf",
        payload=_pdf_payload(),
    )

    assert backend.blobs == {
        "invoices/invoice_A.pdf": _pdf_payload()
    }
    assert handle.locator == "azure://docs/invoices/invoice_A.pdf"
    assert handle.filename == "invoice_A.pdf"
    assert handle.file_size == len(_pdf_payload())


def test_list_documents_scoped_to_session():
    backend = FakeAzureBackend()
    storage = UploadSessionDocumentStorage(backend=backend)

    storage.add_document(
        category="invoices",
        locator="invoices/invoice_A.pdf",
        payload=_pdf_payload(),
    )

    assert [
        handle.locator
        for handle in storage.list_documents("invoices")
    ] == ["azure://docs/invoices/invoice_A.pdf"]
    assert storage.list_documents("contracts") == []


def test_read_bytes_delegates_to_backend():
    backend = FakeAzureBackend()
    storage = UploadSessionDocumentStorage(backend=backend)

    storage.add_document(
        category="contracts",
        locator="contracts/contract_A.pdf",
        payload=_pdf_payload(),
    )

    assert (
        storage.read_bytes(
            "azure://docs/contracts/contract_A.pdf"
        )
        == _pdf_payload()
    )
    assert storage.exists(
        "azure://docs/contracts/contract_A.pdf"
    )
