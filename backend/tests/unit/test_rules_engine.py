"""The categorisation rules engine (BR-07, BR-08)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from finance_app.modules.categories.engine import Rule, categorize, matches, order_rules
from finance_app.modules.categories.models import RuleField, RuleOperator

GROCERIES, EATING_OUT, KIDS = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _rule(
    value: str,
    category: uuid.UUID,
    *,
    user: bool = False,
    field: RuleField = RuleField.DESCRIPTION,
    operator: RuleOperator = RuleOperator.CONTAINS,
    priority: int = 100,
    age_days: int = 0,
) -> Rule:
    return Rule(
        id=uuid.uuid4(),
        match_field=field,
        operator=operator,
        value=value,
        category_id=category,
        is_user_rule=user,
        priority=priority,
        created_at=T0 - timedelta(days=age_days),
    )


def test_builtin_keyword_rule_categorises_br07() -> None:
    rules = order_rules([_rule("TESCO", GROCERIES), _rule("PRET", EATING_OUT)])

    assert categorize("TESCO STORES 2041", "Tesco", rules) == GROCERIES
    assert categorize("PRET A MANGER LONDON", None, rules) == EATING_OUT


def test_no_match_is_uncategorized_br07() -> None:
    assert categorize("SOMETHING ELSE", None, order_rules([_rule("TESCO", GROCERIES)])) is None


def test_user_rule_beats_builtin_rule_br08() -> None:
    rules = order_rules(
        [
            _rule("TESCO", GROCERIES, priority=0),  # built-in, even with a lower priority
            _rule("Tesco", KIDS, user=True, field=RuleField.MERCHANT, priority=500),
        ]
    )

    assert categorize("TESCO STORES 2041", "Tesco", rules) == KIDS


def test_priority_then_newest_first_within_a_group() -> None:
    old_low = _rule("COFFEE", GROCERIES, user=True, priority=10, age_days=30)
    new_high = _rule("COFFEE", EATING_OUT, user=True, priority=50)
    newer_same = _rule("COFFEE", KIDS, user=True, priority=10)

    assert order_rules([new_high, old_low, newer_same]) == [newer_same, old_low, new_high]


@pytest.mark.parametrize(
    ("operator", "value", "text", "expected"),
    [
        (RuleOperator.CONTAINS, "pret", "PRET A MANGER", True),
        (RuleOperator.CONTAINS, "costa", "PRET A MANGER", False),
        (RuleOperator.EQUALS, "pret a manger", "  PRET A MANGER ", True),
        (RuleOperator.EQUALS, "pret", "PRET A MANGER", False),
        (RuleOperator.STARTS_WITH, "pret", "PRET A MANGER", True),
        (RuleOperator.STARTS_WITH, "manger", "PRET A MANGER", False),
    ],
)
def test_operators_are_case_insensitive(
    operator: RuleOperator, value: str, text: str, expected: bool
) -> None:
    assert matches(_rule(value, GROCERIES, operator=operator), text, None) is expected


def test_merchant_rules_ignore_description_and_missing_merchant() -> None:
    rule = _rule("Tesco", GROCERIES, field=RuleField.MERCHANT, operator=RuleOperator.EQUALS)

    assert matches(rule, "anything", "TESCO")
    assert not matches(rule, "TESCO STORES", None)


def test_blank_rule_value_never_matches() -> None:
    assert not matches(_rule("   ", GROCERIES), "anything", "anything")


def test_ties_prefer_the_more_specific_value_then_are_deterministic() -> None:
    short, long_ = _rule("TFL", GROCERIES), _rule("TFL TRAVEL", EATING_OUT)

    assert order_rules([short, long_]) == [long_, short]
    assert order_rules([long_, short]) == [long_, short]
