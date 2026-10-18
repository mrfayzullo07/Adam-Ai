"""3. float32 <-> PCM16 konvertatsiyasi."""
from __future__ import annotations

import numpy as np

from app.utils.audio import (
    float_to_pcm16,
    is_valid_pcm16_chunk,
    pcm16_duration_seconds,
    pcm16_to_float,
    rms_level,
)


def test_roundtrip_preserves_signal() -> None:
    t = np.linspace(0, 0.1, 1600, endpoint=False, dtype=np.float32)
    signal = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    pcm = float_to_pcm16(signal)
    assert len(pcm) == 1600 * 2
    restored = pcm16_to_float(pcm)
    assert restored.dtype == np.float32
    assert np.max(np.abs(restored - signal)) < 1e-4


def test_extremes_and_clipping() -> None:
    pcm = float_to_pcm16(np.array([-1.0, 0.0, 1.0, 2.0, -3.0, np.nan], dtype=np.float32))
    ints = np.frombuffer(pcm, dtype="<i2").tolist()
    assert ints == [-32768, 0, 32767, 32767, -32768, 0]
    assert pcm16_to_float(pcm).tolist()[:3] == [-1.0, 0.0, 1.0]


def test_odd_length_bytes_truncated() -> None:
    assert pcm16_to_float(b"\x01\x00\x02").shape == (1,)


def test_chunk_validation_and_helpers() -> None:
    assert is_valid_pcm16_chunk(b"\x00\x00" * 1600)
    assert not is_valid_pcm16_chunk(b"")
    assert not is_valid_pcm16_chunk(b"\x00\x00\x00")
    assert not is_valid_pcm16_chunk(b"\x00" * (16000 * 2 * 2 + 2))
    assert pcm16_duration_seconds(3200) == 0.1
    assert rms_level(b"") == 0.0
    assert rms_level(float_to_pcm16(np.ones(100, dtype=np.float32))) > 0.99
