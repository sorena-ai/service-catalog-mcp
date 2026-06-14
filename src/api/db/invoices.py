import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from lib.db.mongo import MongoDB

# ---------------------------------------------------------------------------
# Invoice / InvoiceDB (keyed by user_id)
# ---------------------------------------------------------------------------

class Invoice:
    def __init__(
        self,
        user_id: str,
        invoice_type: str,
        amount: float,
        status: str,
        description: str,
        payment_intent_id: Optional[str] = None,
        stripe_charge_id: Optional[str] = None,
        currency: str = "usd",
        created_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
        _id: Optional[str] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.invoice_type = invoice_type
        self.amount = amount
        self.status = status
        self.description = description
        self.payment_intent_id = payment_intent_id
        self.stripe_charge_id = stripe_charge_id
        self.currency = currency
        self.created_at = created_at or datetime.utcnow()
        self.expires_at = expires_at

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "invoice_type": self.invoice_type,
            "amount": self.amount,
            "status": self.status,
            "description": self.description,
            "payment_intent_id": self.payment_intent_id,
            "stripe_charge_id": self.stripe_charge_id,
            "currency": self.currency,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Invoice":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            invoice_type=data["invoice_type"],
            amount=data["amount"],
            status=data["status"],
            description=data["description"],
            payment_intent_id=data.get("payment_intent_id"),
            stripe_charge_id=data.get("stripe_charge_id"),
            currency=data.get("currency", "usd"),
            created_at=data.get("created_at"),
            expires_at=data.get("expires_at"),
        )


class InvoiceDB:
    def __init__(self):
        self.db = MongoDB().connect()
        self.collection = self.db["invoices"]

    def create_invoice(self, invoice: Invoice) -> Dict[str, Any]:
        try:
            doc = invoice.to_dict()
            result = self.collection.insert_one(doc)
            inserted = self.collection.find_one({"_id": result.inserted_id})
            if inserted:
                inserted["_id"] = str(inserted["_id"])
                for f in ("created_at", "expires_at"):
                    if isinstance(inserted.get(f), datetime):
                        inserted[f] = inserted[f].isoformat()
            return inserted or {**doc, "_id": str(result.inserted_id)}
        except Exception as e:
            logging.error("Error creating invoice: %s", e)
            raise

    def get_user_invoices(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            invoices = list(self.collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit))
            for inv in invoices:
                inv["_id"] = str(inv["_id"])
                for f in ("created_at", "expires_at"):
                    if isinstance(inv.get(f), datetime):
                        inv[f] = inv[f].isoformat()
            return invoices
        except Exception as e:
            logging.error("Error getting user invoices: %s", e)
            raise

    def update_invoice_status(self, payment_intent_id: str, status: str, stripe_charge_id: Optional[str] = None) -> bool:
        try:
            update: Dict[str, Any] = {"status": status}
            if stripe_charge_id:
                update["stripe_charge_id"] = stripe_charge_id
            result = self.collection.update_one({"payment_intent_id": payment_intent_id}, {"$set": update})
            return result.modified_count > 0
        except Exception as e:
            logging.error("Error updating invoice status: %s", e)
            raise

    def find_invoice_by_payment_intent(self, payment_intent_id: str) -> Optional[Dict[str, Any]]:
        try:
            inv = self.collection.find_one({"payment_intent_id": payment_intent_id})
            if inv:
                inv["_id"] = str(inv["_id"])
            return inv
        except Exception as e:
            logging.error("Error finding invoice by payment_intent: %s", e)
            raise

