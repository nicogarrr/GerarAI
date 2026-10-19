"""connect_args por motor: el timeout idle-in-transaction es solo Postgres."""

from app.core.database import _engine_connect_args


def test_sqlite_gets_check_same_thread_and_no_timeout():
    assert _engine_connect_args("sqlite:///./x.db", 120000) == {
        "check_same_thread": False
    }


def test_postgres_gets_idle_in_transaction_timeout():
    assert _engine_connect_args("postgresql://u:p@h/db", 120000) == {
        "options": "-c idle_in_transaction_session_timeout=120000"
    }
    assert _engine_connect_args("postgresql+psycopg://u:p@h/db", 45000) == {
        "options": "-c idle_in_transaction_session_timeout=45000"
    }


def test_timeout_zero_disables_and_other_engines_untouched():
    assert _engine_connect_args("postgresql://u:p@h/db", 0) == {}
    assert _engine_connect_args("mysql+pymysql://u:p@h/db", 120000) == {}
