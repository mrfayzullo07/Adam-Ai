"""PCM audio yordamchilari (numpy).

Format: 16-bit signed little-endian, mono.
  INPUT  (client -> Gemini): 16 000 Hz
  OUTPUT (Gemini -> client): 24 000 Hz
"""
from __future__ import annotations

import numpy as np

INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
INPUT_MIME = f"audio/pcm;rate={INPUT_SAMPLE_RATE}"
BYTES_PER_SAMPLE = 2
# Bitta chunk uchun yuqori chegara (~2 soniya 16 kHz da) — suiiste'molni oldini oladi
MAX_INPUT_CHUNK_BYTES = INPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * 2


def float_to_pcm16(samples: np.ndarray) -> bytes:
    """float32 [-1.0, 1.0] massivni int16 little-endian PCM baytlariga aylantiradi."""
    arr = np.asarray(samples, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
    arr = np.clip(arr, -1.0, 1.0)
    # Manfiy tomon 32768 ga, musbat tomon 32767 ga ko'paytiriladi (Web Audio bilan bir xil)
    scaled = np.where(arr < 0, arr * 32768.0, arr * 32767.0)
    return np.round(scaled).astype("<i2").tobytes()


def pcm16_to_float(data: bytes) -> np.ndarray:
    """int16 little-endian PCM baytlarini float32 [-1.0, 1.0] massivga aylantiradi."""
    if len(data) % BYTES_PER_SAMPLE:
        data = data[: len(data) - (len(data) % BYTES_PER_SAMPLE)]
    ints = np.frombuffer(data, dtype="<i2").astype(np.float32)
    return np.where(ints < 0, ints / 32768.0, ints / 32767.0).astype(np.float32)


def is_valid_pcm16_chunk(data: bytes) -> bool:
    """Client'dan kelgan chunk to'g'ri o'lchamdami (juft, bo'sh emas, juda katta emas)."""
    return 0 < len(data) <= MAX_INPUT_CHUNK_BYTES and len(data) % BYTES_PER_SAMPLE == 0


def pcm16_duration_seconds(num_bytes: int, sample_rate: int = INPUT_SAMPLE_RATE) -> float:
    return num_bytes / (BYTES_PER_SAMPLE * sample_rate)


def rms_level(data: bytes) -> float:
    """Chunk ovoz balandligi (0..1) — sukunatni aniqlash uchun."""
    samples = pcm16_to_float(data)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))
