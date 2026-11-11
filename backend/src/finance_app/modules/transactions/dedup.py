"""Deduplication keys for transactions (BR-06).

The key is the provider's transaction ID when there is one. Otherwise it is a
SHA-256 of account, booking date, amount and description, plus an *occurrence
number*: two genuinely identical transactions on the same day (two identical
coffees) would otherwise collide and one would be lost. Banks return transactions
in a stable order, so the n-th identical transaction gets the same key every sync.
"""

import hashlib
import uuid
from collections import Counter
from collections.abc import Sequence

from finance_app.providers.base import ProviderTransaction


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def dedup_keys(account_id: uuid.UUID, transactions: Sequence[ProviderTransaction]) -> list[str]:
    """Compute one key per transaction, in order.

    Args:
        account_id: The account the transactions belong to.
        transactions: One provider response for that account.

    Returns:
        A 64-character hex key for each transaction.
    """
    seen: Counter[str] = Counter()
    keys = []
    for tx in transactions:
        if tx.provider_transaction_id:
            keys.append(_sha256(f"id|{tx.provider_transaction_id}"))
            continue
        fingerprint = "|".join(
            (str(account_id), tx.booking_date.isoformat(), str(tx.amount), tx.description)
        )
        seen[fingerprint] += 1
        keys.append(_sha256(f"tx|{fingerprint}|{seen[fingerprint]}"))
    return keys
