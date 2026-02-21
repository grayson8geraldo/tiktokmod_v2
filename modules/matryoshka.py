"""
Модуль 2: Визуальная «Матрёшка» (Слои).
Формирует трёхслойную композицию:
  - Нижний слой (Background): статичная подложка
  - Средний слой (Main Video): основной контент, масштабированный до 95–98%
  - Верхний слой (Overlay): динамический шум (зерно) с прозрачностью 1–3%
"""

import logging
import os
import random

from config import MatryoshkaConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def process(
    input_path: str,
    output_path: str,
    cfg: MatryoshkaConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Собирает трёхслойную композицию и возвращает путь к результату.
    """
    if not cfg.enabled:
        logger.info("Модуль Matryoshka отключён, пропуск")
        return input_path

    info = get_video_info(ffprobe, input_path)
    duration = info["duration"]
    fps = info["fps"]
    out_w = cfg.output_width
    out_h = cfg.output_height

    # Размер основного видео (уменьшенный)
    scaled_w = int(out_w * cfg.video_scale)
    scaled_h = int(out_h * cfg.video_scale)
    # Обеспечиваем чётность
    scaled_w = scaled_w if scaled_w % 2 == 0 else scaled_w - 1
    scaled_h = scaled_h if scaled_h % 2 == 0 else scaled_h - 1

    # Микро-сдвиг позиции
    jitter_x = random.randint(-cfg.position_jitter, cfg.position_jitter)
    jitter_y = random.randint(-cfg.position_jitter, cfg.position_jitter)
    overlay_x = (out_w - scaled_w) // 2 + jitter_x
    overlay_y = (out_h - scaled_h) // 2 + jitter_y

    # Прозрачность шума (0.01–0.03)
    noise_strength = int(cfg.noise_opacity * 255)

    # Длительность фона с запасом чтобы overlay не обрезал видео
    safe_duration = duration + 10

    # --- Сборка filter_complex ---
    parts = []

    if cfg.background_image and os.path.isfile(cfg.background_image):
        # С фоновым изображением: input0 = видео, input1 = фон
        inputs = [
            "-i", input_path,
            "-loop", "1", "-i", cfg.background_image,
        ]
        video_idx = "0"
        parts.append(
            f"[1:v]scale={out_w}:{out_h}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}[bg]"
        )
    else:
        # Без фонового изображения: серый цвет, input0 = видео
        inputs = ["-i", input_path]
        video_idx = "0"
        parts.append(
            f"color=c=0x404040:s={out_w}x{out_h}:r={fps}:d={safe_duration}[bg]"
        )

    # Масштабирование основного видео
    parts.append(
        f"[{video_idx}:v]scale={scaled_w}:{scaled_h}:"
        f"force_original_aspect_ratio=decrease[main]"
    )

    # Наложение видео на фон (eof_action=endall — завершить когда видео кончится)
    parts.append(
        f"[bg][main]overlay=x={overlay_x}:y={overlay_y}:"
        f"eof_action=endall[composed]"
    )

    # Динамический шум поверх
    parts.append(
        f"[composed]noise=c0s={noise_strength}:allf=t[outv]"
    )

    full_filter = ";".join(parts)

    cmd = [ffmpeg, "-y"]
    cmd.extend(inputs)
    cmd.extend([
        "-filter_complex", full_filter,
        "-map", "[outv]",
        "-map", f"{video_idx}:a?",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ])

    run_cmd(cmd, "сборка матрёшки")

    logger.info(
        "Матрёшка собрана: %dx%d, масштаб %.2f, сдвиг (%+d,%+d), шум %d: %s",
        out_w, out_h, cfg.video_scale, jitter_x, jitter_y, noise_strength,
        output_path,
    )
    return output_path
