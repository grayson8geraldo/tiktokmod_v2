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

    # --- Генерация нулевого сегмента ---
    zero_segment = os.path.join(temp_dir, "_zero_segment.mp4")

    if cfg.mode == "gray":
        # Серый кадр #808080
        run_cmd([
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x808080:s={w}x{h}:d={cfg.duration}:r={fps}",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(cfg.duration),
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            zero_segment,
        ], "генерация серого кадра")
    elif cfg.mode == "image":
        if not cfg.image_path or not os.path.isfile(cfg.image_path):
            raise FileNotFoundError(
                f"Изображение для нулевого кадра не найдено: {cfg.image_path}"
            )
        run_cmd([
            ffmpeg, "-y",
            "-loop", "1", "-i", cfg.image_path,
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(cfg.duration),
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            zero_segment,
        ], "генерация кадра из изображения")
    else:
        raise ValueError(f"Неизвестный режим нулевого кадра: {cfg.mode}")

    # --- Конкатенация ---
    concat_list = os.path.join(temp_dir, "_concat_list.txt")
    with open(concat_list, "w") as f:
        f.write(f"file '{zero_segment}'\n")
        f.write(f"file '{input_path}'\n")

    if cfg.transition == "fade":
        # Конкатенация с плавным переходом:
        # Сначала конкатенируем через concat demuxer, затем fade-in на стыке
        fade_dur = min(cfg.fade_duration, cfg.duration)
        concat_raw = os.path.join(temp_dir, "_concat_raw.mp4")

        # Шаг 1: простая конкатенация
        run_cmd([
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            concat_raw,
        ], "конкатенация для фейда")

        # Шаг 2: fade-out на нулевом сегменте + fade-in на стыке
        fade_start = max(cfg.duration - fade_dur, 0)
        run_cmd([
            ffmpeg, "-y",
            "-i", concat_raw,
            "-vf", f"fade=t=out:st={fade_start}:d={fade_dur},"
                   f"fade=t=in:st={cfg.duration}:d={fade_dur}",
            "-af", f"afade=t=out:st={fade_start}:d={fade_dur},"
                   f"afade=t=in:st={cfg.duration}:d={fade_dur}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            output_path,
        ], "применение фейда на стыке")
    else:
        # Резкий переход — простая конкатенация
        run_cmd([
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            output_path,
        ], "конкатенация с резким переходом")

    logger.info("Нулевой кадр добавлен: %s", output_path)
    return output_path
