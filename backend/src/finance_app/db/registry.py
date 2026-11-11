"""Import every ORM model so ``Base.metadata`` knows the full schema.

Alembic's env.py and the worker import this module; add each new domain's models here.
"""

from finance_app.modules.accounts.models import Account, Balance
from finance_app.modules.audit.models import AuditEvent
from finance_app.modules.auth.models import RefreshToken
from finance_app.modules.budgets.models import Budget
from finance_app.modules.categories.models import Category, CategoryRule
from finance_app.modules.connections.models import BankConnection
from finance_app.modules.notifications.models import Notification
from finance_app.modules.transactions.models import Transaction
from finance_app.modules.users.models import User

__all__ = [
    "Account",
    "AuditEvent",
    "Balance",
    "BankConnection",
    "Budget",
    "Category",
    "CategoryRule",
    "Notification",
    "RefreshToken",
    "Transaction",
    "User",
]
