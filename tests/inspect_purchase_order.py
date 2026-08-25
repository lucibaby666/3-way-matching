import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

from app.env import get_env


load_dotenv()

client = DocumentIntelligenceClient(
    endpoint=get_env("DOCUMENT_INTELLIGENCE_ENDPOINT"),
    credential=AzureKeyCredential(
        get_env("DOCUMENT_INTELLIGENCE_API_KEY")
    ),
)

path = (
    "data/purchase_orders/"
    "purchase_order_PO-2026-1001.pdf"
)

with open(path, "rb") as document:

    poller = client.begin_analyze_document(
        "prebuilt-layout",
        body=document,
    )

result = poller.result()

print("\n===== PARAGRAPHS =====")

for index, paragraph in enumerate(result.paragraphs or []):

    print(f"\n[{index}]")
    print("CONTENT:", paragraph.content)
    print(
        "BOUNDING REGIONS:",
        paragraph.bounding_regions,
    )


print("\n===== TABLES =====")

for table_index, table in enumerate(
    result.tables or []
):

    print(
        f"\nTABLE {table_index}: "
        f"{table.row_count} rows x "
        f"{table.column_count} columns"
    )

    for cell in table.cells:

        print(
            f"ROW={cell.row_index} "
            f"COL={cell.column_index} "
            f"CONTENT={cell.content!r}"
        )

        print(
            "BOUNDING REGIONS:",
            cell.bounding_regions,
        )