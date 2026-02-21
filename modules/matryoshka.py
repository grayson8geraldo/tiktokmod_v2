"""
Модуль Б: Многослойная композиция (Layering).

Слой 1 (Фон): Видео-подложка (якорь, размытый BoxBlur 2-3px).
Слой 2 (Центр): Основное видео, уменьшенное до 94-97%.
Эффект «Края»: Drop shadow под основным видео для стирания
  чёткой границы между слоями.
Мерцание: Видео/Подложка вместо Видео/Чёрный.

Видео-подложка подготавливается anchor_manager заранее.
"""

import logging
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
    background_video: str | None = None,
    flicker_cfg: FlickerConfig | None = None,
) -> str:
    """
    Собирает композицию:
      [bg_video] → фон
      [main_video] → масштабированный + мерцание + shadow → overlay на фон
      [composed] → шум → выход

    background_video: путь к подготовленной видео-подложке (из anchor_manager).
    flicker_cfg: если передан — мерцание встраивается в видеопоток.
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

    # --- Сборка filter_complex ---
    parts = []
    inputs = []

    # Вход 0: основное видео
    # Вход 1: видео-подложка
    if background_video:
        inputs = ["-i", input_path, "-i", background_video]
        # Подложка уже подготовлена anchor_manager (blur, scale, loop)
        parts.append(f"[1:v]null[bg]")
    else:
        # Fallback: серый фон с шумом (если якорь не задан)
        inputs = ["-i", input_path]
        safe_duration = duration + 10
        parts.append(
            f"color=c=0x404040:s={out_w}x{out_h}:r={fps}:d={safe_duration},"
            f"noise=c0s=4:allf=t[bg]"
        )

    # Масштабирование основного видео
    parts.append(
        f"[0:v]scale={scaled_w}:{scaled_h}:"
        f"force_original_aspect_ratio=decrease[scaled]"
    )

    # Мерцание (Soft Interleaving): Видео/Подложка
    # Применяется к [scaled] — делает видео прозрачным, обнажая подложку
    if flicker_cfg is not None:
        flicker_filter = build_flicker_filters(
            flicker_cfg, fps, duration,
            width=scaled_w, height=scaled_h,
            input_label="[scaled]",
            output_label="[flickered]",
        )
        parts.append(flicker_filter)
        video_label = "[flickered]"
    else:
        video_label = "[scaled]"

    # Drop Shadow: создаём чёрный прямоугольник чуть больше видео,
    # размываем его и кладём под видео — имитация тени
    shadow_s = cfg.shadow_strength
    shadow_a = cfg.shadow_opacity
    if shadow_s > 0 and shadow_a > 0:
        # Тень: чёрный прямоугольник размером scaled + 4px с каждой стороны
        shadow_w = scaled_w + shadow_s * 2
        shadow_h = scaled_h + shadow_s * 2
        shadow_w = shadow_w if shadow_w % 2 == 0 else shadow_w - 1
        shadow_h = shadow_h if shadow_h % 2 == 0 else shadow_h - 1

        safe_duration = duration + 10
        # Генерируем чёрный прямоугольник с альфой, размываем
        parts.append(
            f"color=black@{shadow_a}:s={shadow_w}x{shadow_h}:r={fps}:d={safe_duration},"
            f"format=yuva420p,"
            f"boxblur={shadow_s}:{shadow_s}[shadow]"
        )
        # Overlay тени на подложку
        shadow_x = overlay_x - shadow_s
        shadow_y = overlay_y - shadow_s
        parts.append(
            f"[bg][shadow]overlay=x={shadow_x}:y={shadow_y}:"
            f"format=auto:eof_action=endall[bg_shadow]"
        )
        # Overlay видео на подложку с тенью
        # format=auto нужен для корректной обработки альфа-канала мерцания
        parts.append(
            f"[bg_shadow]{video_label}overlay=x={overlay_x}:y={overlay_y}:"
            f"format=auto:eof_action=endall[composed]"
        )
    else:
        # Без тени — просто overlay
        parts.append(
            f"[bg]{video_label}overlay=x={overlay_x}:y={overlay_y}:"
            f"format=auto:eof_action=endall[composed]"
        )

    # Динамический шум (ISO grain)
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
        "Матрёшка: %dx%d, масштаб %.2f, сдвиг (%+d,%+d), шум %d, "
        "тень=%d/%.0f%%, мерцание=%s, подложка=%s: %s",
        out_w, out_h, cfg.video_scale, jitter_x, jitter_y, noise_strength,
        shadow_s, shadow_a * 100,
        "да" if flicker_cfg else "нет",
        "видео" if background_video else "серый",
        output_path,
    )
    return output_path
