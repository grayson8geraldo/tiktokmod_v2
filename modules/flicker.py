"""
Модуль: Кадровое мерцание (Flicker).

Мягкое мерцание для обхода детекции при сохранении смотрибельности:
  - Alpha-blending: тёмные кадры сохраняют 15-20% видимости (не 100% чёрный)
  - Motion blur: tblend сглаживает стыки между кадрами
  - Паттерн 2-1-2: 2 видимых → 1 тёмный → 2 видимых (вместо 1:1)
  - Сдвиг фазы: пачка тёмных кадров каждые N секунд

Этот модуль генерирует FFmpeg filter фрагмент для применения
к видеопотоку. Может использоваться как самостоятельно, так и встроенным
в filter_complex матрёшки (для мерцания только на видео, не на подложке).
"""

import logging

from config import FlickerConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def build_flicker_filters(cfg: FlickerConfig, fps: float,
                          input_label: str = "[0:v]",
                          output_label: str = "[flickered]") -> str:
    """
    Строит цепочку FFmpeg-фильтров для мерцания.

    Использует drawbox с альфа-каналом (color=black@ALPHA) для мягкого
    затемнения, а не полностью чёрный кадр. Затем tblend для motion blur.

    Паттерн: visible_frames видимых, затем dark_frames затемнённых.
    На затемнённых кадрах видео видно на dark_opacity (0.18 = 18%).
    """
    vis = cfg.visible_frames     # 2
    dark = cfg.dark_frames       # 1
    cycle = vis + dark           # 3
    opacity = cfg.dark_opacity   # 0.18
    # Прозрачность чёрного = 1 - opacity (0.82 = 82% чёрного, 18% видео)
    black_alpha = 1.0 - opacity

    phase_interval_frames = int(fps * cfg.phase_shift_interval)
    burst = cfg.phase_shift_dark_frames

    # --- Условие затемнения ---
    # Кадр n затемняется если:
    #   1) mod(n, cycle) >= visible_frames  (паттерн 2-1-2)
    #   2) mod(n, phase_interval) < burst   (пачка тёмных на сдвиге фазы)
    cond_pattern = f"gte(mod(n\\,{cycle})\\,{vis})"
    cond_phase = f"lt(mod(n\\,{phase_interval_frames})\\,{burst})"

    # Объединяем: затемнить если ЛЮБОЕ условие истинно
    enable_expr = f"'{cond_pattern}+{cond_phase}'"

    # --- drawbox с альфа-каналом ---
    # color=black@0.82 = 82% непрозрачный чёрный → 18% оригинала видно
    drawbox_filter = (
        f"drawbox=x=0:y=0:w=iw:h=ih:"
        f"color=black@{black_alpha:.2f}:t=fill:"
        f"enable={enable_expr}"
    )

    # --- Сборка цепочки ---
    parts = []

    # drawbox для alpha-blending
    parts.append(f"{input_label}{drawbox_filter}[_fl_box]")

    # tblend для motion blur (сглаживание стыков)
    if cfg.motion_blur:
        parts.append(f"[_fl_box]tblend=all_mode=average{output_label}")
    else:
        parts.append(f"[_fl_box]null{output_label}")

    return ";".join(parts)


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

    filter_str = build_flicker_filters(
        cfg, fps,
        input_label="[0:v]",
        output_label="[outv]",
    )

    logger.info(
        "Мерцание: паттерн %d/%d, opacity=%.0f%%, blur=%s, phase=%ds/%d",
        cfg.visible_frames, cfg.dark_frames,
        cfg.dark_opacity * 100, cfg.motion_blur,
        cfg.phase_shift_interval, cfg.phase_shift_dark_frames,
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
