"""Gibrid CEFR daraja algoritmi.

Har sessiya oxirida backend skorlar, davomiylik va xatolar asosida "progress ball"
hisoblaydi va `users.level_progress` (0-100) ga qo'shadi. 100% ga yetganda daraja oshadi.
Adam'ning `suggest_level` tavsiyasi faqat bonus/jarima sifatida ta'sir qiladi —
yakuniy qaror shu algoritmda.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

# Yuqori darajalarda o'sish sekinroq
LEVEL_SPEED: dict[str, float] = {"A1": 1.0, "A2": 0.9, "B1": 0.8, "B2": 0.7, "C1": 0.6, "C2": 0.0}

MIN_DURATION_FOR_PROGRESS = 60  # soniya
FULL_SESSION_SECONDS = 600  # 10 daqiqa = to'liq vazn
MAX_GAIN = 25.0
MAX_LOSS = -10.0
SUGGESTION_BONUS = 10.0
SEVERITY_PENALTY: dict[str, float] = {"low": 0.0, "medium": 0.5, "high": 1.5}
MAX_ERROR_PENALTY = 10.0


def normalize_level(level: str | None) -> str:
    lvl = (level or "").strip().upper()
    return lvl if lvl in CEFR_LEVELS else "A1"


def next_level(level: str) -> str | None:
    idx = CEFR_LEVELS.index(normalize_level(level))
    return CEFR_LEVELS[idx + 1] if idx + 1 < len(CEFR_LEVELS) else None


def level_index(level: str) -> int:
    return CEFR_LEVELS.index(normalize_level(level))


@dataclass(slots=True)
class LevelResult:
    level: str
    progress: int
    gain: float
    leveled_up: bool


def average_score(scores: Mapping[str, int | None]) -> float | None:
    vals = [v for v in scores.values() if v is not None]
    return sum(vals) / len(vals) if vals else None


def compute_gain(
    *,
    level: str,
    scores: Mapping[str, int | None],
    duration_seconds: int,
    error_severities: list[str],
    suggested_level: str | None = None,
) -> float:
    """Sessiya uchun progress balli (manfiy bo'lishi ham mumkin)."""
    level = normalize_level(level)
    avg = average_score(scores)
    if duration_seconds < MIN_DURATION_FOR_PROGRESS or avg is None:
        return 0.0

    weight = min(duration_seconds / FULL_SESSION_SECONDS, 1.0)
    base = (avg - 2.5) * 10.0  # 1 -> -15, 3 -> +5, 5 -> +25
    penalty = min(sum(SEVERITY_PENALTY.get(s, 0.5) for s in error_severities), MAX_ERROR_PENALTY)
    gain = (base - penalty) * weight

    if suggested_level:
        diff = level_index(suggested_level) - level_index(level)
        if diff > 0:
            gain += SUGGESTION_BONUS
        elif diff < 0:
            gain -= SUGGESTION_BONUS

    if gain > 0:
        gain *= LEVEL_SPEED[level]
    return max(MAX_LOSS, min(MAX_GAIN, gain))


def apply_gain(level: str, progress: int, gain: float) -> LevelResult:
    """Ballni joriy progressga qo'shadi; 100 dan oshsa keyingi darajaga o'tkazadi.

    Daraja avtomatik pasaytirilmaydi — progress 0 dan pastga tushmaydi.
    """
    level = normalize_level(level)
    if next_level(level) is None:
        return LevelResult(level=level, progress=100, gain=gain, leveled_up=False)

    new_progress = progress + gain
    if new_progress >= 100:
        return LevelResult(
            level=next_level(level) or level,
            progress=int(min(new_progress - 100, 50)),
            gain=gain,
            leveled_up=True,
        )
    return LevelResult(level=level, progress=int(max(0, round(new_progress))), gain=gain, leveled_up=False)


def project_level(
    *,
    level: str,
    progress: int,
    scores: Mapping[str, int | None],
    duration_seconds: int,
    error_severities: list[str],
    suggested_level: str | None = None,
) -> LevelResult:
    """Sessiya davomida "hozir tugatsa nima bo'ladi" prognozi (UI uchun)."""
    gain = compute_gain(
        level=level,
        scores=scores,
        duration_seconds=duration_seconds,
        error_severities=error_severities,
        suggested_level=suggested_level,
    )
    return apply_gain(level, progress, gain)
