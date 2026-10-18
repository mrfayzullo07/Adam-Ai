"""Max tarifi: guruhdagi matn/ovozli savollarga javob va kanal uchun kunlik dars."""
from __future__ import annotations

from datetime import date
from html import escape

from google.genai import types
from pydantic import BaseModel, Field

from app.gemini.text import generate, text_models

GROUP_SYSTEM = """You are Adam, a friendly English tutor for Uzbek speakers, answering inside a Telegram group.
Always answer in Uzbek (Latin script) and give English examples where useful.
What you do:
- Translate Uzbek <-> English (give the natural translation, plus 1 short alternative if helpful).
- Correct English mistakes: show "❌ wrong → ✅ correct" and explain why in one short Uzbek sentence.
- Explain words, phrases and grammar simply, with 1-2 examples (English + Uzbek translation).
- For a voice message: first write what the person said ("🗣 ..."), then correct/answer it, and give
  short pronunciation tips if you notice problems.
Rules: plain text only (NO markdown, no **, no #), max ~120 words, emojis sparingly.
If the message is not about learning English, answer in one polite sentence and invite an English question."""


async def answer_group_message(
    text: str,
    *,
    context: str | None = None,
    voice: bytes | None = None,
    voice_mime: str = "audio/ogg",
    asker: str = "",
) -> str:
    parts: list[types.Part | str] = []
    if context:
        parts.append(f"Message being replied to (context):\n{context[:1500]}")
    if voice:
        parts.append(types.Part.from_bytes(data=voice, mime_type=voice_mime))
        parts.append("The learner sent this voice message." + (f" Extra text: {text}" if text else ""))
    else:
        parts.append(f"Learner {asker}: {text[:2000]}")
    resp = await generate(
        parts,
        models=text_models(),
        config=types.GenerateContentConfig(system_instruction=GROUP_SYSTEM, temperature=0.4, max_output_tokens=600),
    )
    out = (resp.text or "").strip()
    return out.replace("**", "").replace("__", "") or "Kechirasiz, javob tayyorlay olmadim. Savolni qayta yozing 🙏"


class Example(BaseModel):
    en: str
    uz: str


class QuizItem(BaseModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=4)
    answer: str


class DailyLesson(BaseModel):
    word: str
    transcription: str
    part_of_speech: str
    meaning_uz: str
    examples: list[Example] = Field(min_length=2, max_length=3)
    phrase_en: str
    phrase_uz: str
    phrase_usage_uz: str
    grammar_tip_uz: str
    quiz: list[QuizItem] = Field(min_length=3, max_length=3)


LESSON_PROMPT = """Create today's short English lesson for an Uzbek Telegram channel (date: {day}).
Level: A2-B1. Pick a useful everyday word (not too basic), a common phrase/idiom, one short grammar tip,
and a 3-question multiple-choice quiz that tests today's content. All explanations in Uzbek (Latin script).
Vary topics day to day (use the date as inspiration). Return JSON matching the schema."""


async def generate_daily_lesson(day: date, bot_username: str | None = None) -> str:
    resp = await generate(
        LESSON_PROMPT.format(day=day.isoformat()),
        models=text_models(),
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=DailyLesson, temperature=0.9
        ),
    )
    lesson = resp.parsed if isinstance(resp.parsed, DailyLesson) else DailyLesson.model_validate_json(resp.text or "{}")
    return format_lesson(lesson, day, bot_username)


def format_lesson(lesson: DailyLesson, day: date, bot_username: str | None = None) -> str:
    """Telegram HTML posti (javoblar spoiler ostida)."""
    e = escape
    examples = "\n".join(f"• {e(x.en)}\n  <i>{e(x.uz)}</i>" for x in lesson.examples)
    letters = "ABCD"
    quiz_lines: list[str] = []
    answers: list[str] = []
    for i, q in enumerate(lesson.quiz, 1):
        opts = "  ".join(f"{letters[j]}) {e(o)}" for j, o in enumerate(q.options))
        quiz_lines.append(f"{i}. {e(q.question)}\n   {opts}")
        answers.append(f"{i}) {e(q.answer)}")
    return (
        f"📚 <b>Kunlik ingliz tili darsi</b> — {day:%d.%m.%Y}\n\n"
        f"📌 <b>Kun so'zi:</b> <b>{e(lesson.word)}</b> {e(lesson.transcription)} <i>({e(lesson.part_of_speech)})</i>\n"
        f"— {e(lesson.meaning_uz)}\n{examples}\n\n"
        f"💬 <b>Kun iborasi:</b> {e(lesson.phrase_en)}\n— {e(lesson.phrase_uz)}\n<i>{e(lesson.phrase_usage_uz)}</i>\n\n"
        f"🧩 <b>Grammatika:</b> {e(lesson.grammar_tip_uz)}\n\n"
        f"🧠 <b>Mini test</b>\n" + "\n".join(quiz_lines) + "\n\n"
        f"✅ Javoblar: <tg-spoiler>{'  '.join(answers)}</tg-spoiler>\n\n"
        "🎤 Adam bilan ovozli mashq qiling" + (f": @{e(bot_username)}" if bot_username else "!")
    )
