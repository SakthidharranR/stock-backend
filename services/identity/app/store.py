import logging
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


class UserStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self):
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            yield conn

    def create_user(self, cognito_sub: str, email: str, display_name: str) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (cognito_sub, email, display_name)
                    VALUES (%s, %s, %s)
                    """,
                    (cognito_sub, email, display_name),
                )
            conn.commit()

    def upsert_user(self, cognito_sub: str, email: str, display_name: str) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (cognito_sub, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cognito_sub) DO UPDATE SET
                        email = EXCLUDED.email,
                        display_name = EXCLUDED.display_name,
                        updated_at = now()
                    """,
                    (cognito_sub, email, display_name),
                )
            conn.commit()

    def get_user_by_cognito_sub(self, cognito_sub: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, cognito_sub, email, display_name FROM users WHERE cognito_sub = %s",
                    (cognito_sub,),
                )
                return cur.fetchone()

    def get_user_by_email(self, email: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, cognito_sub, email, display_name FROM users WHERE lower(email) = lower(%s)",
                    (email.strip(),),
                )
                return cur.fetchone()

    def ping(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")


def open_store(database_url: str) -> UserStore:
    store = UserStore(database_url)
    store.ping()
    return store
