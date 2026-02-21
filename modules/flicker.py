"""
Модуль: Кадровое мерцание (Flicker).

Мягкое мерцание для обхода детекции при сохранении смотрибельности:
  - Alpha-blending: тёмные кадры сохраняют 15-20% видимости (не 100% чёрный)
  - Motion blur: tblend сглаживает стыки между кадрами
  - Паттерн 2-1-2: 2 видимых → 1 тёмный → 2 видимых (вместо 1:1)
  - Сдвиг фазы: пачка тёмных кадров каждые N секунд

Этот модуль генерирует FFmpeg filter_complex фрагмент для применения
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

    Возвращает строку filter_complex фрагмента:
      [input_label] → geq (alpha-blending) → tblend (motion blur) → [output_label]

    Паттерн: visible_frames видимых, затем dark_frames затемнённых.
    На затемнённых кадрах видео видно на dark_opacity (0.18 = 18%).
    """
    vis = cfg.visible_frames     # 2
    dark = cfg.dark_frames       # 1
    cycle = vis + dark           # 3
    opacity = cfg.dark_opacity   # 0.18

    phase_interval_frames = int(fps * cfg.phase_shift_interval)
    burst = cfg.phase_shift_dark_frames

    # --- Условие затемнения ---
    # Кадр n затемняется если:
    #   1) mod(n, cycle) >= visible_frames  (паттерн 2-1-2)
    #   2) mod(n, phase_interval) < burst   (пачка тёмных на сдвиге фазы)
    cond_pattern = f"gte(mod(n\\,{cycle})\\,{vis})"
    cond_phase = f"lt(mod(n\\,{phase_interval_frames})\\,{burst})"
    # is_dark = 1 если хотя бы одно условие (сумма > 0 → gt > 0)
    is_dark = f"gt({cond_pattern}+{cond_phase}\\,0)"

    # --- Alpha-blending через geq ---
    # Для светлых кадров: factor = 1.0 (без изменений)
    # Для тёмных кадров: factor = dark_opacity (0.18)
    # factor = 1 - is_dark * (1 - opacity)
    # Применяем к каждому каналу: p(X,Y) * factor
    factor = f"(1-{is_dark}*{1.0 - opacity:.2f})"
    geq_filter = (
        f"geq="
        f"lum='lum(X\\,Y)*{factor}':"
        f"cb='cb(X\\,Y)':"
        f"cr='cr(X\\,Y)'"
    )

    # --- Сборка цепочки ---
    strip_input = input_label
    parts = []

    # geq для alpha-blending
    parts.append(f"{strip_input}{geq_filter}[_fl_geq]")

    # tblend для motion blur (сглаживание стыков)
    if cfg.motion_blur:
        parts.append(f"[_fl_geq]tblend=all_mode=average{output_label}")
    else:
        # Без motion blur — просто переименовываем
        parts.append(f"[_fl_geq]null{output_label}")

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
