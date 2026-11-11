from pydantic import SecretStr

from finance_app.core.config import Environment, Settings


def test_database_url_uses_asyncpg_and_masks_password() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_password=SecretStr("s3cret"),
        postgres_host="db",
    )

    url = settings.database_url

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db"
    assert "s3cret" not in repr(url)
    assert "s3cret" not in repr(settings)


def test_is_production_only_in_production() -> None:
    base = {"_env_file": None, "postgres_password": SecretStr("x")}

    assert Settings(**base, environment=Environment.PRODUCTION).is_production  # type: ignore[arg-type]
    assert not Settings(**base, environment=Environment.LOCAL).is_production  # type: ignore[arg-type]
