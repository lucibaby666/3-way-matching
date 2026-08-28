from typing import Any, Dict, List, Optional

from app.models.contract import Contract
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.models.source_reference import SourceReference


class Canonicalizer:
    """
    Converts lightweight extraction results into canonical
    application domain models.

    This layer isolates extraction-specific structures from
    the deterministic matching engine.
    """

    def canonicalize_source(
        self,
        source: Optional[Dict[str, Any]],
        document_id: str,
        document_path: str,
    ) -> Optional[SourceReference]:
        """
        Convert a lightweight extraction source into
        a SourceReference domain object.
        """

        if not source:
            return None

        locations = source.get("source", [])

        if not locations:
            return None

        location = locations[0]

        return SourceReference(
            document_id=document_id,
            document_path=document_path,
            page_number=location["page_number"],
            polygon=location["polygon"],
        )

    def canonicalize_contract(
        self,
        extracted: Dict[str, Any],
        document_id: str,
    ) -> Contract:
        """
        Convert ContractExtractor output into Contract.
        """

        document_path = extracted.get("document_path", "")

        return Contract(
            contract_id=document_id,

            contract_number=self._value(
                extracted.get("contract_number")
            ),

            contract_date=self._value(
                extracted.get("contract_date")
            ),

            buyer=self._value(
                extracted.get("buyer")
            ),

            supplier=self._value(
                extracted.get("supplier")
            ),

            contract_validity=self._value(
                extracted.get("contract_validity")
            ),

            payment_terms=self._value(
                extracted.get("payment_terms")
            ),

            quantity_tolerance=self._value(
                extracted.get("quantity_tolerance")
            ),

            price_tolerance=self._value(
                extracted.get("price_tolerance")
            ),

            invoice_rule=self._value(
                extracted.get("invoice_rule")
            ),

            line_items=[
                self._canonicalize_line_item(
                    item,
                    document_id,
                    document_path,
                )
                for item in extracted.get(
                    "line_items",
                    [],
                )
            ],

            source=self.canonicalize_source(
                extracted.get("contract_number"),
                document_id,
                document_path,
            ),
        )

    def canonicalize_purchase_order(
        self,
        extracted: Dict[str, Any],
        document_id: str,
    ) -> PurchaseOrder:
        """
        Convert PurchaseOrderExtractor output into
        the canonical PurchaseOrder model.
        """
    
        document_path = extracted.get("document_path", "")
    
        return PurchaseOrder(
            po_id=document_id,
    
            po_number=self._value(
                extracted.get("po_number")
            ),
    
            contract_reference=self._value(
                extracted.get("contract_reference")
            ),
    
            po_date=self._value(
                extracted.get("po_date")
            ),
    
            buyer=self._value(
                extracted.get("buyer")
            ),
    
            supplier=self._value(
                extracted.get("supplier")
            ),
    
            line_items=[
                self._canonicalize_line_item(
                    item,
                    document_id,
                    document_path,
                )
                for item in extracted.get(
                    "line_items",
                    [],
                )
            ],
    
            source=self.canonicalize_source(
                extracted.get("po_number"),
                document_id,
                document_path,
            ),
        )

    def canonicalize_invoice(
        self,
        extracted: Dict[str, Any],
        document_id: str,
    ) -> Invoice:
        """
        Convert InvoiceExtractor output into Invoice.
        """

        document_path = extracted.get("document_path", "")

        return Invoice(
            invoice_id=document_id,

            invoice_number=self._value(
                extracted.get("invoice_number")
            ),

            purchase_order_reference=self._value(
                extracted.get(
                    "purchase_order"
                )
            ),

            invoice_date=self._value(
                extracted.get("invoice_date")
            ),

            due_date=self._value(
                extracted.get("due_date")
            ),

            vendor=self._value(
                extracted.get("vendor_name")
            ),

            customer=self._value(
                extracted.get("customer_name")
            ),

            subtotal=self._numeric_value(
                extracted.get("subtotal")
            ),

            total_tax=self._numeric_value(
                extracted.get("total_tax")
            ),

            total=self._currency_value(
                extracted.get("invoice_total")
            ),

            line_items=[
                self._canonicalize_line_item(
                    item,
                    document_id,
                    document_path,
                )
                for item in extracted.get(
                    "line_items",
                    [],
                )
            ],

            source=self.canonicalize_source(
                extracted.get("invoice_number"),
                document_id,
                document_path,
            ),
        )

    def _canonicalize_line_item(
        self,
        extracted: Dict[str, Any],
        document_id: str,
        document_path: str,
    ) -> LineItem:
        """
        Convert an extracted line item into the
        shared canonical LineItem.
        """

        return LineItem(
            item_code=self._value(
                extracted.get("item_code")
            ),

            description=self._value(
                extracted.get("description")
            ),

            quantity=self._numeric_value(
                extracted.get("quantity")
            ),

            unit=self._value(
                extracted.get("unit")
            ),

            unit_price=self._numeric_value(
                extracted.get("unit_price")
            ),

            tax=self._numeric_value(
                extracted.get("tax")
            ),

            amount=self._numeric_value(
                extracted.get("amount")
            ),

            source=self.canonicalize_source(
                extracted.get("quantity")
                or extracted.get("description")
                or extracted.get("item_code"),
                document_id,
                document_path,
            ),
        )

    @staticmethod
    def _value(
        field: Optional[Dict[str, Any]],
    ) -> Optional[Any]:
        """
        Extract the value from a {value, source} structure.
        """

        if field is None:
            return None

        return field.get("value")

    @classmethod
    def _numeric_value(
        cls,
        field: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        """
        Convert an extracted numeric value into float.
        """

        value = cls._value(field)

        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        value = str(value).replace(",", "").strip()

        if value.endswith("%"):
            value = value[:-1]

        try:
            return float(value)
        except ValueError:
            return None

    @classmethod
    def _currency_value(
        cls,
        field: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        """
        Convert Azure currency field into a numeric amount.
        """

        value = cls._value(field)

        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, dict):
            amount = value.get("amount")

            if amount is not None:
                return float(amount)

        text = str(value)

        # Fallback for values such as:
        # INR 76,700.00
        text = (
            text.replace(",", "")
            .replace("INR", "")
            .strip()
        )

        try:
            return float(text)
        except ValueError:
            return None