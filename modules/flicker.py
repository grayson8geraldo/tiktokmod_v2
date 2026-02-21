"""
Модуль: Кадровое мерцание (Flicker) v2.

Принципиальные отличия от v1:
  1. Overlay с переменной прозрачностью вместо drawbox.
     Чёрный слой с alpha, модулированным sin(), оставляет 10-30%
     видимости видео — мягче для модерации.

  2. Рандомизация «битых тактов».
     Интервал между пачками: случайный (1.8–2.4 сек).
     Длительность пачки: случайная (2–4 кадра).
     Каждое видео — уникальная структура таймлайна.

  3. Motion blur (tblend) для сглаживания стыков.

Этот модуль генерирует FFmpeg filter фрагмент для применения
к видеопотоку. Может использоваться как самостоятельно, так и встроенным
в filter_complex матрёшки (для мерцания только на видео, не на подложке).
"""

import logging
import random

from config import FlickerConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def _generate_burst_schedule(
    duration: float, fps: float, cfg: FlickerConfig,
) -> list[tuple[int, int]]:
    """
    Предварительно вычисляет рандомизированное расписание пачек затемнения.

    Возвращает список (start_frame, end_frame) — включительно.
    Интервалы и длительности рандомизированы, так что каждый вызов
    даёт уникальную структуру таймлайна.
    """
    schedule = []
    total_frames = int(duration * fps)
    current_frame = 0

    while current_frame < total_frames:
        # Случайный интервал до следующей пачки
        interval_sec = random.uniform(cfg.burst_interval_min, cfg.burst_interval_max)
        current_frame += int(interval_sec * fps)

        if current_frame >= total_frames:
            break

        # Случайная длительность пачки
        burst_len = random.randint(cfg.burst_frames_min, cfg.burst_frames_max)
        end_frame = min(current_frame + burst_len - 1, total_frames - 1)

        schedule.append((current_frame, end_frame))
        current_frame = end_frame + 1

    return schedule


def build_flicker_filters(
    cfg: FlickerConfig,
    fps: float,
    duration: float,
    width: int,
    height: int,
    input_label: str = "[0:v]",
    output_label: str = "[flickered]",
) -> str:
    """
    Строит цепочку FFmpeg-фильтров для мерцания с overlay.

    Подход:
      1. Генерируем маленький (4x4) чёрный источник с альфа-каналом.
      2. geq задаёт alpha с sin-модуляцией (0 вне пачек, 0.7–0.9 внутри).
      3. Масштабируем до размеров видео (nearest neighbor — быстро).
      4. overlay на исходное видео.
      5. Опционально tblend для motion blur.

    Рандомизация:
      Расписание пачек вычисляется заранее в Python (random),
      а в FFmpeg передаётся как серия between(N,start,end).
    """
    schedule = _generate_burst_schedule(duration, fps, cfg)

    if not schedule:
        logger.warning("Расписание мерцания пустое (видео слишком короткое?)")
        return f"{input_label}null{output_label}"

    # --- Условие: «мы внутри какой-либо пачки» ---
    # В geq переменные с большой буквы: N = номер кадра, T = время
    # Собираем OR из between(N,start,end)
    conditions = [f"between(N,{s},{e})" for s, e in schedule]
    is_dark_expr = "+".join(conditions)

    # --- Alpha с sin-модуляцией ---
    # Прозрачность чёрного плавно гуляет между alpha_min и alpha_max.
    # sin даёт «дрожание» в пределах пачки, а не резкое включение/выключение.
    # Период ~0.15 сек — достаточно быстро для видимого «flutter».
    alpha_mid = (cfg.alpha_min + cfg.alpha_max) / 2
    alpha_amp = (cfg.alpha_max - cfg.alpha_min) / 2
    sin_period = 0.15

    # alpha_expr даёт значение 0..1 (доля чёрного)
    alpha_expr = f"{alpha_mid:.3f}+{alpha_amp:.3f}*sin(2*PI*T/{sin_period:.2f})"

    # В geq: a = 0..255. Внутри пачки = alpha*255, вне = 0 (полностью прозрачный)
    # Внутри одинарных кавычек запятые не нужно экранировать
    geq_alpha = f"if({is_dark_expr},255*({alpha_expr}),0)"

    safe_dur = duration + 10

    parts = []

    # 1. Маленький чёрный источник → альфа через geq → масштаб
    parts.append(
        f"color=black:s=4x4:r={fps}:d={safe_dur},"
        f"format=yuva420p,"
        f"geq=lum=0:cb=128:cr=128:a='{geq_alpha}',"
        f"scale={width}:{height}:flags=neighbor"
        f"[_fl_dark]"
    )

    # 2. Overlay чёрного слоя на видео
    parts.append(
        f"{input_label}[_fl_dark]overlay=format=auto[_fl_ov]"
    )

    # 3. Motion blur (сглаживание стыков)
    if cfg.motion_blur:
        parts.append(f"[_fl_ov]tblend=all_mode=average{output_label}")
    else:
        parts.append(f"[_fl_ov]null{output_label}")

    filter_str = ";".join(parts)

    logger.info(
        "Мерцание: %d пачек, alpha=%.0f–%.0f%%, burst=%d–%d кадров, "
        "интервал=%.1f–%.1fс, blur=%s",
        len(schedule),
        cfg.alpha_min * 100, cfg.alpha_max * 100,
        cfg.burst_frames_min, cfg.burst_frames_max,
        cfg.burst_interval_min, cfg.burst_interval_max,
        cfg.motion_blur,
    )

    return filter_str


def process(
    input_path: str,
    output_path: str,
    cfg: FlickerConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Применяет мерцание к видеофайлу (самостоятельный режим, без подложки).
    """
    info = get_video_info(ffprobe, input_path)
    fps = info["fps"]
    duration = info["duration"]
    w = info["width"]
    h = info["height"]

    filter_str = build_flicker_filters(
        cfg, fps, duration,
        width=w, height=h,
        input_label="[0:v]",
        output_label="[outv]",
    )

    run_cmd([
        ffmpeg, "-y",
        "-i", input_path,
        "-filter_complex", filter_str,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "кадровое мерцание")

    logger.info("Мерцание применено: %s", output_path)
    return output_path
