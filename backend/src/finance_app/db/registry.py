"""Import every ORM model so ``Base.metadata`` knows the full schema.

Alembic's env.py imports this module; add each new domain's models here.
"""

from finance_app.modules.auth.models import RefreshToken
from finance_app.modules.users.models import User

__all__ = ["RefreshToken", "User"]
