"""
Модуль 5: Аудио-обработка.
  - Pitch Shift: изменение тональности на ±0.1–0.3 полутона без изменения длительности
  - Volume Noise: наложение фонового розового шума на минимальной громкости
"""

import logging
import math
import os
import random

from config import AudioConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def _semitones_to_rate(semitones: float) -> float:
    """Конвертирует полутоны в коэффициент частоты для asetrate."""
    return 2.0 ** (semitones / 12.0)


def process(
    input_path: str,
    output_path: str,
    cfg: AudioConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Применяет pitch shift и наложение розового шума.
    """
    if not cfg.enabled:
        logger.info("Модуль Audio отключён, пропуск")
        return input_path

    info = get_video_info(ffprobe, input_path)

    if not info["has_audio"]:
        logger.info("Аудиодорожка отсутствует, пропуск аудио-модуля")
        import shutil
        shutil.copy2(input_path, output_path)
        return output_path

    # --- Определение направления pitch shift ---
    shift = cfg.pitch_shift_semitones
    if cfg.pitch_direction == "random":
        direction = random.choice([-1, 1])
    elif cfg.pitch_direction == "down":
        direction = -1
    else:
        direction = 1

    actual_shift = shift * direction
    rate_factor = _semitones_to_rate(actual_shift)

    logger.info(
        "Pitch shift: %+.2f полутона (коэффициент %.6f)",
        actual_shift, rate_factor,
    )

    # --- Аудио-фильтр ---
    # Pitch shift без изменения длительности:
    # asetrate для изменения частоты + aresample для возврата к исходной
    # rubberband фильтр — лучше, но требует librubberband
    # Используем asetrate + atempo для компенсации

    # asetrate меняет pitch, но и скорость.
    # Чтобы компенсировать скорость, используем atempo=1/rate_factor
    atempo_factor = 1.0 / rate_factor

    # atempo принимает значения 0.5–2.0, наш диапазон ±0.3 полутона
    # даёт rate_factor ~0.983–1.017, atempo ~0.983–1.017 — в допустимом диапазоне

    sample_rate = 44100  # стандартная частота

    audio_filters = []

    # Pitch shift
    audio_filters.append(f"asetrate={sample_rate}*{rate_factor:.6f}")
    audio_filters.append(f"atempo={atempo_factor:.6f}")
    audio_filters.append(f"aresample={sample_rate}")

    # --- Розовый шум ---
    # Генерируем розовый шум через anoisesrc и микшируем
    # Розовый шум: anoisesrc с типом pink
    pink_vol_db = cfg.pink_noise_volume_db
    logger.info("Розовый шум: громкость %+.1f дБ", pink_vol_db)

    # Строим filter_complex с двумя входами
    af_chain = ",".join(audio_filters)

    duration = info["duration"]

    filter_complex = (
        f"[0:a]{af_chain}[shifted];"
        f"anoisesrc=sample_rate={sample_rate}:color=pink:d={duration},"
        f"volume={pink_vol_db}dB[noise];"
        f"[shifted][noise]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )

    run_cmd([
        ffmpeg, "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ], "аудио обработка (pitch + шум)")

    logger.info("Аудио обработано: %s", output_path)
    return output_path
