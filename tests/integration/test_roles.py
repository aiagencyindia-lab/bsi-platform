from bsi_core.config import get_settings
from sqlalchemy import create_engine, text


def test_app_role_cannot_bypass_rls():
    eng = create_engine(get_settings().database_url)
    with eng.connect() as c:
        row = c.execute(
            text(
                "SELECT rolbypassrls, rolsuper FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).one()
    assert row == (False, False)


def test_urls_point_at_test_database():
    assert get_settings().database_url.endswith("/bsi_test")
