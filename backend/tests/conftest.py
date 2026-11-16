import os

import psycopg2
import pytest

# 必须在导入 app 之前切换到独立测试库
os.environ["DATABASE_URL"] = "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/epv_test"
os.environ["JWT_SECRET"] = "test-secret"


def _ensure_test_db():
    conn = psycopg2.connect(host="127.0.0.1", user="ccdev", password="ccdev", dbname="ccdev")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname='epv_test'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE epv_test")
    conn.close()


_ensure_test_db()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import run as seed_run  # noqa: E402


@pytest.fixture(scope="session")
def client():
    seed_run(reset=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture(scope="session")
def H(token):
    return {"Authorization": f"Bearer {token}"}
