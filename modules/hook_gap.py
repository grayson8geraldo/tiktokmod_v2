"""
Модуль А: Подготовка начала (The Hook Gap).

Динамический серый фон с микро-шумом вместо заливки #808080.
Аудио: Pink Noise (комнатный тон) на ~1% громкости вместо тишины.
Crossfade 0.1 сек в следующий сегмент.

Длительность: 0.3–0.6 сек.
"""

import logging

from config import HookGapConfig
from modules.utils import run_cmd

logger = logging.getLogger(__name__)


def generate_hook_gap(
    output_path: str,
    cfg: HookGapConfig,
    ffmpeg: str,
    w: int,
    h: int,
    fps: float,
) -> str:
    """
    Генерирует сегмент Hook Gap: серый фон с динамическим шумом + pink noise.

    Вместо color=0x808080 используем color + noise filter для динамичности.
    Аудио — anoisesrc pink на минимальной громкости (комнатный тон).
    """
    duration = cfg.duration

    # --- Видео: серый фон + динамический шум ---
    # noise filter с allf=t даёт temporal noise (разный каждый кадр)
    noise_s = cfg.noise_strength
    vf = (
        f"noise=c0s={noise_s}:allf=t"
    )

    # Fade-out в конце для crossfade с якорем
    cf_dur = cfg.crossfade_duration
    if cf_dur > 0:
        fade_start = max(duration - cf_dur, 0)
        vf += f",fade=t=out:st={fade_start}:d={cf_dur}"

    # --- Аудио: pink noise (комнатный тон, ~1% громкости) ---
    pink_db = cfg.pink_noise_db
    af = f"volume={pink_db}dB"
    if cf_dur > 0:
        fade_start = max(duration - cf_dur, 0)
        af += f",afade=t=out:st={fade_start}:d={cf_dur}"

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x808080:s={w}x{h}:d={duration}:r={fps}",
        "-f", "lavfi",
        "-i", f"anoisesrc=sample_rate=44100:color=pink:d={duration}",
        "-vf", vf,
        "-af", af,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    run_cmd(cmd, "генерация Hook Gap")

    logger.info(
        "Hook Gap: %.2fс, шум=%d, pink_noise=%.0fdB, crossfade=%.2fс: %s",
        duration, noise_s, pink_db, cf_dur, output_path,
    )
    return output_path
