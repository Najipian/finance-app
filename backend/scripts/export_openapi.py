"""Export the API's OpenAPI schema to docs/openapi.json.

The web app generates its TypeScript types from this file (``npm run gen:api``), and
CI checks both are up to date. Uses throwaway settings: no secrets or services needed.

Run from ``backend/``: ``uv run python scripts/export_openapi.py``
"""

import json
from pathlib import Path

from pydantic import SecretStr

from finance_app.core.config import Settings
from finance_app.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def main() -> None:
    """Write the schema with stable formatting (sorted keys, trailing newline)."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_password=SecretStr("unused"),
        jwt_secret=SecretStr("unused-" * 6),
        token_encryption_key=SecretStr("A" * 43 + "="),
        bank_provider="mock",
    )
    schema = create_app(settings).openapi()
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
