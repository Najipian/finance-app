"""The categorisation rules engine (BR-07). Pure functions, no I/O.

Rules are tried in order and the first match wins:

1. the user's own rules before built-in ones (a user's rule always wins),
2. then lower ``priority`` first,
3. then newest first,
4. then the longer (more specific) value, then ID, so the order is never undefined:
   built-in rules share a priority and creation time.

Matching is case-insensitive. No match means *Uncategorized* (``None``).
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from finance_app.modules.categories.models import RuleField, RuleOperator


@dataclass(frozen=True, slots=True)
class Rule:
    """A rule as the engine sees it."""

    id: uuid.UUID
    match_field: RuleField
    operator: RuleOperator
    value: str
    category_id: uuid.UUID
    is_user_rule: bool
    priority: int
    created_at: datetime


def order_rules(rules: Iterable[Rule]) -> list[Rule]:
    """Sort rules into evaluation order (see module docstring)."""
    return sorted(
        rules,
        key=lambda r: (
            not r.is_user_rule,
            r.priority,
            -r.created_at.timestamp(),
            -len(r.value.strip()),
            str(r.id),
        ),
    )


def matches(rule: Rule, description: str, merchant: str | None) -> bool:
    """Whether one rule matches a transaction (case-insensitive)."""
    text = (merchant if rule.match_field is RuleField.MERCHANT else description) or ""
    text, value = text.casefold().strip(), rule.value.casefold().strip()
    if not value:
        return False
    if rule.operator is RuleOperator.EQUALS:
        return text == value
    if rule.operator is RuleOperator.STARTS_WITH:
        return text.startswith(value)
    return value in text


def categorize(
    description: str, merchant: str | None, ordered_rules: Sequence[Rule]
) -> uuid.UUID | None:
    """The category of the first matching rule, or None (Uncategorized).

    Args:
        description: Transaction description.
        merchant: Merchant name, if the bank provided one.
        ordered_rules: Rules already sorted by ``order_rules``.
    """
    for rule in ordered_rules:
        if matches(rule, description, merchant):
            return rule.category_id
    return None
