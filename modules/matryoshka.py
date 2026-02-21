"""
Модуль: Визуальная «Матрёшка» (Слои).

Формирует композицию:
  - Нижний слой (Background): подложка (картинка или серый цвет)
  - Средний слой (Main Video): основное видео (опционально с мерцанием)
  - Верхний слой: динамический шум

Мерцание применяется к видеопотоку ДО наложения на подложку,
поэтому подложка всегда остаётся видимой.
"""

import logging
import os
import random

from config import MatryoshkaConfig, FlickerConfig
from modules.flicker import build_flicker_filters
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def process(
    input_path: str,
    output_path: str,
    cfg: MatryoshkaConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
    background_image: str | None = None,
    flicker_cfg: FlickerConfig | None = None,
) -> str:
    """
    Собирает композицию и возвращает путь к результату.

    background_image: путь к картинке-подложке (None = серый фон 0x404040)
    flicker_cfg: если передан — мерцание встраивается в видеопоток до overlay
    """
    info = get_video_info(ffprobe, input_path)
    duration = info["duration"]
    fps = info["fps"]
    out_w = cfg.output_width
    out_h = cfg.output_height

    # Размер основного видео (уменьшенный)
    scaled_w = int(out_w * cfg.video_scale)
    scaled_h = int(out_h * cfg.video_scale)
    scaled_w = scaled_w if scaled_w % 2 == 0 else scaled_w - 1
    scaled_h = scaled_h if scaled_h % 2 == 0 else scaled_h - 1

    # Микро-сдвиг позиции
    jitter_x = random.randint(-cfg.position_jitter, cfg.position_jitter)
    jitter_y = random.randint(-cfg.position_jitter, cfg.position_jitter)
    overlay_x = (out_w - scaled_w) // 2 + jitter_x
    overlay_y = (out_h - scaled_h) // 2 + jitter_y

    noise_strength = int(cfg.noise_opacity * 255)
    safe_duration = duration + 10

    # --- Сборка filter_complex ---
    parts = []
    inputs = []

    if background_image and os.path.isfile(background_image):
        inputs = ["-i", input_path, "-loop", "1", "-i", background_image]
        parts.append(
            f"[1:v]scale={out_w}:{out_h}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}[bg]"
        )
    else:
        inputs = ["-i", input_path]
        parts.append(
            f"color=c=0x404040:s={out_w}x{out_h}:r={fps}:d={safe_duration}[bg]"
        )

    # Масштабирование видео
    parts.append(
        f"[0:v]scale={scaled_w}:{scaled_h}:"
        f"force_original_aspect_ratio=decrease[scaled]"
    )

    # Мерцание (если включено) — применяется к [scaled] ДО наложения на подложку
    if flicker_cfg is not None:
        flicker_filter = build_flicker_filters(
            flicker_cfg, fps,
            input_label="[scaled]",
            output_label="[main]",
        )
        parts.append(flicker_filter)
    else:
        parts.append("[scaled]null[main]")

    # Overlay видео на подложку
    parts.append(
        f"[bg][main]overlay=x={overlay_x}:y={overlay_y}:"
        f"eof_action=endall[composed]"
    )

    # Динамический шум
    parts.append(
        f"[composed]noise=c0s={noise_strength}:allf=t[outv]"
    )

    full_filter = ";".join(parts)

    cmd = [ffmpeg, "-y"]
    cmd.extend(inputs)
    cmd.extend([
        "-filter_complex", full_filter,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ])

    run_cmd(cmd, "сборка матрёшки")

    logger.info(
        "Матрёшка: %dx%d, масштаб %.2f, сдвиг (%+d,%+d), шум %d, мерцание=%s: %s",
        out_w, out_h, cfg.video_scale, jitter_x, jitter_y, noise_strength,
        "да" if flicker_cfg else "нет", output_path,
    )
    return output_path
