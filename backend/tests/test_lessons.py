"""Vaziyatli darslar: katalog, /api/lessons, prompt va WS topic integratsiyasi."""
from __future__ import annotations

from urllib.parse import quote

from fastapi.testclient import TestClient
from google.genai import types

from app.gemini.prompt import build_system_prompt
from app.gemini.tools import response_scheduling
from app.lessons.catalog import CATEGORIES, all_topic_ids, get_topic
from app.main import app
from tests.conftest import make_init_data
from tests.test_ws import fake_live  # noqa: F401


def _prompt(topic_id: str | None) -> str:
    return build_system_prompt(
        user_name="Ali", cefr_level="A2", level_progress=0, recent_errors=[], last_session_summary=None,
        mode="free", topic_id=topic_id,
    )


def test_catalog_ids_unique_and_complete() -> None:
    ids = all_topic_ids()
    assert len(ids) == len(set(ids)) and len(ids) >= 40
    for c in CATEGORIES:
        assert c.topics
        for t in c.topics:
            assert t.level in {"A1", "A2", "B1", "B2", "C1", "C2"}
            assert t.situation and t.adam_role and t.task and t.grammar and len(t.phrases) >= 4
    assert {"school", "work", "travel", "shop", "street", "events"} <= {c.id for c in CATEGORIES}


def test_prompt_includes_lesson_only_when_topic_selected() -> None:
    _, topic = get_topic("school_first_day")  # type: ignore[misc]
    with_topic = _prompt("school_first_day")
    assert "TODAY'S LESSON" in with_topic and topic.situation in with_topic and topic.phrases[0] in with_topic
    assert "{lesson_rules}" not in with_topic
    plain = _prompt(None)
    assert "TODAY'S LESSON" not in plain and "{lesson_rules}" not in plain
    assert "TODAY'S LESSON" not in _prompt("unknown_topic")


def test_tool_scheduling_silent_except_set_level() -> None:
    assert response_scheduling("log_error") == types.FunctionResponseScheduling.SILENT
    assert response_scheduling("update_scores") == types.FunctionResponseScheduling.SILENT
    assert response_scheduling("set_level") == types.FunctionResponseScheduling.WHEN_IDLE


def test_lessons_endpoint_marks_recommended() -> None:
    with TestClient(app) as client:
        raw = make_init_data(9101, "Dilnoza")
        res = client.get("/api/lessons", headers={"Authorization": f"tma {raw}"})
        assert res.status_code == 200
        body = res.json()
        assert body["level"] == "A1"
        topics = [t for c in body["categories"] for t in c["topics"]]
        assert len(topics) == len(all_topic_ids())
        assert all(t["recommended"] == (t["level"] in {"A1", "A2"}) for t in topics)


def test_ws_topic_reaches_prompt_and_ready(fake_live) -> None:  # noqa: F811
    with TestClient(app) as client:
        init = quote(make_init_data(9102, "Sardor"), safe="")
        with client.websocket_connect(f"/ws/audio?init_data={init}&topic=travel_airport") as conn:
            ready = conn.receive_json()
            assert ready["type"] == "ready"
            conn.send_json({"type": "end"})
        _, topic = get_topic("travel_airport")  # type: ignore[misc]
        assert ready["topic"]["id"] == "travel_airport"
        assert topic.situation in fake_live["prompt"]
