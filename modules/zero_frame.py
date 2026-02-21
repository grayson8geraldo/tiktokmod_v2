"""
Модуль 1: Подготовка «нулевого» кадра.
Вставляет технический/безопасный сегмент в начало видео.
"""

import logging
import os

from config import ZeroFrameConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def process(
    input_path: str,
    output_path: str,
    cfg: ZeroFrameConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Генерирует нулевой сегмент и конкатенирует с основным видео.
    Возвращает путь к выходному файлу.
    """
    if not cfg.enabled:
        logger.info("Модуль ZeroFrame отключён, пропуск")
        return input_path

    info = get_video_info(ffprobe, input_path)
    w, h, fps = info["width"], info["height"], info["fps"]

    fade_dur = min(cfg.fade_duration, cfg.duration) if cfg.transition == "fade" else 0

    # --- Генерация нулевого сегмента ---
    zero_segment = os.path.join(temp_dir, "_zero_segment.mp4")

    # VF-фильтр: fade-out в конце сегмента (если плавный переход)
    vf_zero = ""
    af_zero = ""
    if fade_dur > 0:
        fade_start = max(cfg.duration - fade_dur, 0)
        vf_zero = f"-vf,fade=t=out:st={fade_start}:d={fade_dur}"
        af_zero = f"-af,afade=t=out:st={fade_start}:d={fade_dur}"

    if cfg.mode == "gray":
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x808080:s={w}x{h}:d={cfg.duration}:r={fps}",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(cfg.duration),
        ]
        if fade_dur > 0:
            cmd.extend(["-vf", f"fade=t=out:st={max(cfg.duration - fade_dur, 0)}:d={fade_dur}"])
            cmd.extend(["-af", f"afade=t=out:st={max(cfg.duration - fade_dur, 0)}:d={fade_dur}"])
        cmd.extend([
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            zero_segment,
        ])
        run_cmd(cmd, "генерация серого кадра")

    elif cfg.mode == "image":
        if not cfg.image_path or not os.path.isfile(cfg.image_path):
            raise FileNotFoundError(
                f"Изображение для нулевого кадра не найдено: {cfg.image_path}"
            )
        scale_filter = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        if fade_dur > 0:
            scale_filter += f",fade=t=out:st={max(cfg.duration - fade_dur, 0)}:d={fade_dur}"

        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-i", cfg.image_path,
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(cfg.duration),
            "-vf", scale_filter,
        ]
        if fade_dur > 0:
            cmd.extend(["-af", f"afade=t=out:st={max(cfg.duration - fade_dur, 0)}:d={fade_dur}"])
        cmd.extend([
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            zero_segment,
        ])
        run_cmd(cmd, "генерация кадра из изображения")
    else:
        raise ValueError(f"Неизвестный режим нулевого кадра: {cfg.mode}")

    # --- Подготовка основного видео (fade-in в начале, если плавный переход) ---
    if fade_dur > 0:
        video_prepared = os.path.join(temp_dir, "_video_fadein.mp4")
        run_cmd([
            ffmpeg, "-y",
            "-i", input_path,
            "-vf", f"fade=t=in:st=0:d={fade_dur}",
            "-af", f"afade=t=in:st=0:d={fade_dur}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            video_prepared,
        ], "fade-in основного видео")
    else:
        video_prepared = input_path

    # --- Конкатенация ---
    concat_list = os.path.join(temp_dir, "_concat_list.txt")
    with open(concat_list, "w") as f:
        f.write(f"file '{zero_segment}'\n")
        f.write(f"file '{video_prepared}'\n")

    run_cmd([
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "конкатенация сегментов")

    logger.info("Нулевой кадр добавлен: %s", output_path)
    return output_path
