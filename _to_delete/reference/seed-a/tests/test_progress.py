from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_lessons_listed():
    lessons = client.get("/lessons").json()
    assert len(lessons) == 5
    assert lessons[0]["id"] == "l-01"


def test_progress_percentage():
    body = client.get("/students/s-003/progress").json()
    assert body["completed"] == 3
    assert body["total"] == 5
    assert body["percentage"] == 60


def test_unknown_student_404():
    assert client.get("/students/nope/progress").status_code == 404


def test_record_progress():
    resp = client.post("/students/s-004/progress", json={"lesson_id": "l-01", "score": 80})
    assert resp.json() == {"ok": True}
    assert client.get("/students/s-004/progress").json()["completed"] == 1
