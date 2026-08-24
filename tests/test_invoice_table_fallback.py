from types import SimpleNamespace

from app.capabilities.invoice_extractor import (
    InvoiceExtractor,
)


def make_cell(
    row_index,
    column_index,
    content,
    page=1,
    polygon=(0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0),
):
    return SimpleNamespace(
        row_index=row_index,
        column_index=column_index,
        content=content,
        bounding_regions=[
            SimpleNamespace(
                page_number=page,
                polygon=list(polygon),
            )
        ],
    )


def make_table(rows):
    cells = []

    for row_index, row in enumerate(rows):
        for column_index, content in enumerate(row):
            cells.append(
                make_cell(
                    row_index,
                    column_index,
                    content,
                )
            )

    return SimpleNamespace(
        row_count=len(rows),
        column_count=len(rows[0]),
        cells=cells,
    )


def merged_items():
    return [
        {
            "item_code": {
                "value": "FIB-001\nFIB-002\nFIB-003",
                "source": [],
            },
        }
    ]


def test_detects_merged_item_codes():
    assert (
        InvoiceExtractor._line_items_are_merged(
            merged_items()
        )
        is True
    )


def test_clean_items_are_not_merged():
    items = [
        {
            "item_code": {
                "value": "FIB-001",
                "source": [],
            },
        }
    ]

    assert (
        InvoiceExtractor._line_items_are_merged(items)
        is False
    )


def test_rebuilds_line_items_from_tables():
    table = make_table(
        [
            [
                "Line",
                "Item Code",
                "Description",
                "Qty",
                "Unit",
                "Unit Price (INR)",
                "Amount (INR)",
            ],
            [
                "1",
                "FIB-001",
                "Single-Mode Fiber Cable",
                "13200",
                "Meter",
                "145.00",
                "1,914,000.00",
            ],
            [
                "2",
                "FIB-002",
                "Distribution Box",
                "40",
                "Each",
                "18,500.00",
                "740,000.00",
            ],
        ]
    )

    extractor = InvoiceExtractor.__new__(
        InvoiceExtractor
    )

    line_items = (
        extractor._extract_line_items_from_tables(
            [table]
        )
    )

    assert len(line_items) == 2

    first = line_items[0]

    assert first["item_code"]["value"] == "FIB-001"
    assert first["quantity"]["value"] == "13200"
    assert first["unit"]["value"] == "Meter"
    assert first["unit_price"]["value"] == "145.00"
    assert first["amount"]["value"] == "1,914,000.00"

    second = line_items[1]

    assert second["item_code"]["value"] == "FIB-002"
    assert second["quantity"]["value"] == "40"


def test_row_union_polygon_spans_columns():
    table = make_table(
        [
            ["Item Code", "Qty"],
            ["FIB-001", "13200"],
        ]
    )

    # Widen the qty cell so the union must span both.
    table.cells[3].bounding_regions[0].polygon = [
        5.0,
        1.0,
        7.0,
        1.0,
        7.0,
        2.0,
        5.0,
        2.0,
    ]

    extractor = InvoiceExtractor.__new__(
        InvoiceExtractor
    )

    columns = extractor._table_columns(table)

    assert columns["item_code"] == 0
    assert columns["quantity"] == 1

    line_items = (
        extractor._extract_line_items_from_tables(
            [table]
        )
    )

    quantity_source = line_items[0][
        "quantity"
    ]["source"]

    assert len(quantity_source) == 1

    xs = [
        point["x"]
        for point in quantity_source[0]["polygon"]
    ]

    assert min(xs) < 1.0
    assert max(xs) >= 7.0


def test_ignores_tables_without_item_code_column():
    table = make_table(
        [
            ["Totals", "Value"],
            ["Subtotal", "100"],
        ]
    )

    extractor = InvoiceExtractor.__new__(
        InvoiceExtractor
    )

    assert (
        extractor._extract_line_items_from_tables(
            [table]
        )
        == []
    )
