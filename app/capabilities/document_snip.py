from pathlib import Path
from typing import List

import fitz  # PyMuPDF
from PIL import Image

from app.storage.document_io import read_document_bytes
from app.storage.document_storage import DocumentStorage
from app.storage.locator import locator_extension


class DocumentSnip:
    """
    Creates visual evidence snippets from PDF documents.

    Input:
        - document locator (local path or Azure blob URI)
        - page number
        - Azure Document Intelligence polygon

    Output:
        - PNG image containing the relevant document region
    """

    def __init__(
        self,
        storage: DocumentStorage | None = None,
    ):
        self.storage = storage

    def create_snip(
        self,
        document_path: str,
        page_number: int,
        polygon: List[dict[str, float]],
        output_path: str,
        padding: float = 0.15,
    ) -> str:
        """
        Create a PNG snip from a PDF page.

        Azure DI coordinates are assumed to be in inches,
        which is the coordinate system used by the current
        POC documents.
        """

        payload = read_document_bytes(
            document_path,
            storage=self.storage,
        )

        if page_number < 1:
            raise ValueError(
                "page_number must be >= 1"
            )

        if not polygon:
            raise ValueError(
                "polygon cannot be empty"
            )

        filetype = locator_extension(document_path).lstrip(".") or "pdf"

        document = fitz.open(
            stream=payload,
            filetype=filetype,
        )

        try:
            if page_number > len(document):
                raise ValueError(
                    f"Page {page_number} does not exist. "
                    f"Document has {len(document)} page(s)."
                )

            page = document[page_number - 1]

            xs = [point["x"] for point in polygon]
            ys = [point["y"] for point in polygon]

            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)

            width = max_x - min_x
            height = max_y - min_y

            # Add context around the extracted region.
            min_x -= width * padding
            max_x += width * padding
            min_y -= height * padding
            max_y += height * padding

            # Keep crop inside the page.
            page_rect = page.rect

            min_x = max(min_x, page_rect.x0)
            min_y = max(min_y, page_rect.y0)
            max_x = min(max_x, page_rect.x1)
            max_y = min(max_y, page_rect.y1)

            crop_rect = fitz.Rect(
                min_x * 72,
                min_y * 72,
                max_x * 72,
                max_y * 72,
            )

            # Render at 2x resolution for readable evidence.
            matrix = fitz.Matrix(2, 2)

            pixmap = page.get_pixmap(
                matrix=matrix,
                clip=crop_rect,
                alpha=False,
            )

            output = Path(output_path)
            output.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            pixmap.save(str(output))

            # Verify that the generated image is readable.
            with Image.open(output) as image:
                image.verify()

            return str(output)

        finally:
            document.close()
