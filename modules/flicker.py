"""
Модуль 3: Кадровое мерцание (Interleaving).
Реализация алгоритма прерывания видеопотока чёрными кадрами:
  - Чередование: [Видео: 1 кадр] -> [Чёрный: 1 кадр]
  - Сдвиг фазы: каждые N секунд — 3 последовательных чёрных кадра
"""

import logging
import os
import struct
import tempfile

from config import FlickerConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def _build_flicker_script(
    total_frames: int,
    fps: float,
    interleave_every: int,
    phase_shift_interval: float,
    phase_shift_black_frames: int,
) -> str:
    """
    Генерирует FFmpeg select-выражение для мерцания.

    Логика:
    - Каждый чётный кадр — показываем, нечётный — заменяем чёрным
    - Каждые phase_shift_interval секунд — вставляем пачку чёрных кадров

    Используем подход через geq + select для реализации.
    Возвращаем скрипт для filtergraph.
    """
    phase_shift_frame_interval = int(fps * phase_shift_interval)

    # Строим выражение: показываем кадр если он подходит под паттерн
    # Чередование: mod(n, interleave_every) == 0
    # Пауза: если кадр попадает в окно паузы, пропускаем
    # В FFmpeg select нельзя «вставить» кадры, поэтому используем другой подход:
    # мы создадим покадровый скрипт через drawbox с условием

    return phase_shift_frame_interval


def process(
    input_path: str,
    output_path: str,
    cfg: FlickerConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Применяет кадровое мерцание к видео.
    """
    if not cfg.enabled:
        logger.info("Модуль Flicker отключён, пропуск")
        return input_path

    info = get_video_info(ffprobe, input_path)
    fps = info["fps"]
    total_frames = info["total_frames"]

    phase_interval_frames = int(fps * cfg.phase_shift_interval)
    black_burst = cfg.phase_shift_black_frames

    # Стратегия: используем drawbox для «зачернения» кадров по условию.
    # Кадр n зачерняется если:
    #   1) mod(n, 2) == 1  (каждый второй кадр — чёрный)  [interleave]
    #   2) кадр попадает в «паузу»: для каждого интервала phase_interval_frames
    #      кадры [k*interval .. k*interval + black_burst - 1] зачерняются
    #
    # FFmpeg drawbox с enable-условием:
    #   enable='between(n, start, end)' или enable='eq(mod(n,2),1)'
    #
    # Комбинируем через несколько drawbox:
    # 1. Чередование — drawbox на каждый нечётный кадр
    # 2. Паузы — серия drawbox для каждого окна паузы

    # Собираем все условия в один geq или серию drawbox
    # Лучший подход: использовать один drawbox с выражением enable

    # Условие чередования
    interleave_cond = f"eq(mod(n\\,{cfg.interleave_every})\\,1)"

    # Условия пауз — генерируем для каждого интервала
    pause_conditions = []
    frame = 0
    while frame < total_frames:
        start = frame
        end = frame + black_burst - 1
        pause_conditions.append(f"between(n\\,{start}\\,{end})")
        frame += phase_interval_frames

    # Объединяем условия пауз через +
    if pause_conditions:
        pause_expr = "+".join(pause_conditions)
        combined = f"{interleave_cond}+{pause_expr}"
    else:
        combined = interleave_cond

    # drawbox зачерняет весь кадр когда условие > 0
    w, h = info["width"], info["height"]
    filter_str = (
        f"drawbox=x=0:y=0:w={w}:h={h}:color=black:t=fill:"
        f"enable='gt({combined}\\,0)'"
    )

    run_cmd([
        ffmpeg, "-y",
        "-i", input_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "кадровое мерцание")

    logger.info("Мерцание применено: %s", output_path)
    return output_path
