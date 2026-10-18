"""4. tool_call handling: validatsiya, DB yozuvi va client eventlari."""
from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.gemini.prompt import ErrorContext, build_system_prompt
from app.gemini.tools import TOOL_DECLARATIONS, handle_function_call
from app.models import Error, User, Vocabulary


async def test_log_error_persists_and_emits_event(user_and_session) -> None:
    user, session, state = user_and_session
    result = await handle_function_call(
        "log_error",
        {"error_type": "grammar", "wrong": "I am go", "correct": "I am going", "severity": "high", "explanation_uz": "-ing kerak"},
        state,
        SessionLocal,
    )
    assert result.response == {"result": "ok"}
    assert result.events[0]["type"] == "error"
    assert result.events[0]["correct"] == "I am going"
    assert state.error_severities == ["high"]

    async with SessionLocal() as db:
        rows = (await db.execute(select(Error).where(Error.session_id == session.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == user.id and rows[0].explanation == "-ing kerak"


async def test_log_error_normalizes_invalid_enums(user_and_session) -> None:
    _, _, state = user_and_session
    result = await handle_function_call(
        "log_error", {"error_type": "spelling", "wrong": "a", "correct": "b", "severity": "fatal"}, state, SessionLocal
    )
    assert result.events[0]["error_type"] == "grammar"
    assert result.events[0]["severity"] == "medium"

    ignored = await handle_function_call("log_error", {"error_type": "grammar", "wrong": "", "correct": "x"}, state, SessionLocal)
    assert ignored.response["result"] == "ignored" and not ignored.events


async def test_update_scores_clamps_and_projects_level(user_and_session) -> None:
    _, _, state = user_and_session
    result = await handle_function_call(
        "update_scores", {"fluency": 9, "grammar": 0, "pronunciation": "3", "comprehension": 4.6}, state, SessionLocal
    )
    assert state.score_updates == [{"fluency": 5, "grammar": 1, "pronunciation": 3, "comprehension": 5}]
    types_ = [e["type"] for e in result.events]
    assert types_ == ["scores", "level_update"]


async def test_record_vocabulary_upserts(user_and_session) -> None:
    user, _, state = user_and_session
    first = await handle_function_call("record_vocabulary", {"word": " Delicious! "}, state, SessionLocal)
    second = await handle_function_call("record_vocabulary", {"word": "delicious"}, state, SessionLocal)
    assert first.events[0]["is_new"] is True
    assert second.events[0]["is_new"] is False and second.events[0]["times_used"] == 2
    async with SessionLocal() as db:
        vocab = (await db.execute(select(Vocabulary).where(Vocabulary.user_id == user.id))).scalars().all()
    assert [v.word for v in vocab] == ["delicious"]
    assert state.vocabulary == ["delicious"]


async def test_suggest_level_and_unknown_tool(user_and_session) -> None:
    _, _, state = user_and_session
    res = await handle_function_call("suggest_level", {"level": "b1", "reason": "yaxshi"}, state, SessionLocal)
    assert state.suggested_level == "B1" and res.response["result"] == "noted"
    unknown = await handle_function_call("delete_everything", {}, state, SessionLocal)
    assert "error" in unknown.response


def test_declarations_and_prompt() -> None:
    assert {d.name for d in TOOL_DECLARATIONS} == {
        "log_error", "update_scores", "record_vocabulary", "suggest_level", "set_level"
    }
    prompt = build_system_prompt(
        user_name="Ali",
        cefr_level="A2",
        level_progress=42,
        recent_errors=[ErrorContext("grammar", "he go", "he goes")],
        last_session_summary=None,
        mode="ptt",
    )
    assert "Foydalanuvchi joriy CEFR darajasi: A2 (keyingi darajagacha 42%)" in prompt
    assert '"he go" -> "he goes"' in prompt
    assert "bu birinchi sessiya" in prompt
    assert "{" not in prompt.split("--- DINAMIK CONTEXT ---")[1]
    assert "MOSTLY UZBEK" in prompt and "ALWAYS UNDERSTAND" in prompt
    assert "PLACEMENT TEST" not in prompt
    for placeholder in ("{language_rules}", "{pace_rules}", "{goal_text}", "{placement_rules}"):
        assert placeholder not in prompt

    placement = build_system_prompt(
        user_name="Ali", cefr_level="A1", level_progress=0, recent_errors=[], last_session_summary=None,
        mode="free", explain_lang="en", speech_pace="normal", goal="ielts", placement=True,
    )
    assert "PLACEMENT TEST" in placement and "MOSTLY ENGLISH" in placement and "IELTS" in placement
    assert "noma'lum (daraja testi kerak)" in placement


async def test_set_level_only_in_placement(user_and_session) -> None:
    user, _, state = user_and_session
    ignored = await handle_function_call("set_level", {"level": "B1"}, state, SessionLocal)
    assert ignored.response["result"] == "ignored"

    state.placement = True
    res = await handle_function_call("set_level", {"level": "b1", "reason": "yaxshi"}, state, SessionLocal)
    assert res.events[0] == {"type": "placement_result", "level": "B1", "next_level": "B2", "progress": 0, "reason": "yaxshi"}
    assert state.level == "B1" and state.placement_done
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
    assert u.cefr_level == "B1" and u.needs_placement is False
