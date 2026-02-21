"""
Модуль: Подготовка вступительных сегментов.

Генерирует вступительные сегменты (серый кадр, картинка) и конкатенирует
их с основным видео. Фейды применяются к каждому сегменту отдельно.
"""

import logging
import os

from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def _generate_gray_segment(
    ffmpeg: str,
    output_path: str,
    w: int, h: int, fps: float,
    duration: float,
    fade_out: bool = True,
    fade_duration: float = 0.2,
) -> str:
    """Генерирует серый (#808080) сегмент."""
    vf = ""
    af = ""
    if fade_out and fade_duration > 0:
        st = max(duration - fade_duration, 0)
        vf = f"-vf,fade=t=out:st={st}:d={fade_duration}"
        af = f"-af,afade=t=out:st={st}:d={fade_duration}"

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x808080:s={w}x{h}:d={duration}:r={fps}",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
    ]
    if fade_out and fade_duration > 0:
        st = max(duration - fade_duration, 0)
        cmd.extend(["-vf", f"fade=t=out:st={st}:d={fade_duration}"])
        cmd.extend(["-af", f"afade=t=out:st={st}:d={fade_duration}"])
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        output_path,
    ])
    run_cmd(cmd, "генерация серого сегмента")
    return output_path


def _generate_image_segment(
    ffmpeg: str,
    image_path: str,
    output_path: str,
    w: int, h: int, fps: float,
    duration: float,
    fade_in: bool = True,
    fade_out: bool = True,
    fade_duration: float = 0.2,
) -> str:
    """Генерирует сегмент из изображения."""
    if not image_path or not os.path.isfile(image_path):
        raise FileNotFoundError(f"Изображение не найдено: {image_path}")

    vf_parts = [
        f"scale={w}:{h}:force_original_aspect_ratio=decrease",
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
    ]
    if fade_in and fade_duration > 0:
        vf_parts.append(f"fade=t=in:st=0:d={fade_duration}")
    if fade_out and fade_duration > 0:
        st = max(duration - fade_duration, 0)
        vf_parts.append(f"fade=t=out:st={st}:d={fade_duration}")

    cmd = [
        ffmpeg, "-y",
        "-loop", "1", "-i", image_path,
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", ",".join(vf_parts),
    ]
    af_parts = []
    if fade_in and fade_duration > 0:
        af_parts.append(f"afade=t=in:st=0:d={fade_duration}")
    if fade_out and fade_duration > 0:
        st = max(duration - fade_duration, 0)
        af_parts.append(f"afade=t=out:st={st}:d={fade_duration}")
    if af_parts:
        cmd.extend(["-af", ",".join(af_parts)])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        output_path,
    ])
    run_cmd(cmd, "генерация сегмента из изображения")
    return output_path


def _apply_fadein(
    ffmpeg: str,
    input_path: str,
    output_path: str,
    fade_duration: float,
) -> str:
    """Применяет fade-in к началу видео."""
    run_cmd([
        ffmpeg, "-y",
        "-i", input_path,
        "-vf", f"fade=t=in:st=0:d={fade_duration}",
        "-af", f"afade=t=in:st=0:d={fade_duration}",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "fade-in")
    return output_path


def _concat_segments(
    ffmpeg: str,
    segments: list[str],
    output_path: str,
    temp_dir: str,
) -> str:
    """Конкатенирует список сегментов."""
    concat_list = os.path.join(temp_dir, "_concat_list.txt")
    with open(concat_list, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    run_cmd([
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "конкатенация сегментов")
    return output_path


def build_intro(
    input_path: str,
    output_path: str,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
    gray_duration: float = 0.0,
    gray_transition: str = "fade",
    gray_fade_duration: float = 0.2,
    image_path: str | None = None,
    image_duration: float = 0.0,
    image_transition: str = "fade",
    image_fade_duration: float = 0.2,
) -> str:
    """
    Собирает вступление (серый + картинка) и конкатенирует с основным видео.

    Можно указать только серый, только картинку, или оба.
    Если ничего — возвращает input_path без изменений.
    """
    info = get_video_info(ffprobe, input_path)
    w, h, fps = info["width"], info["height"], info["fps"]

    segments = []

    # Серый сегмент
    if gray_duration > 0:
        gray_seg = os.path.join(temp_dir, "_intro_gray.mp4")
        _generate_gray_segment(
            ffmpeg, gray_seg, w, h, fps,
            duration=gray_duration,
            fade_out=(gray_transition == "fade"),
            fade_duration=gray_fade_duration,
        )
        segments.append(gray_seg)
        logger.info("Серый сегмент: %.1f сек", gray_duration)

    # Картинка-сегмент
    if image_path and image_duration > 0:
        img_seg = os.path.join(temp_dir, "_intro_image.mp4")
        _generate_image_segment(
            ffmpeg, image_path, img_seg, w, h, fps,
            duration=image_duration,
            fade_in=(image_transition == "fade" and gray_duration > 0),
            fade_out=(image_transition == "fade"),
            fade_duration=image_fade_duration,
        )
        segments.append(img_seg)
        logger.info("Картинка-сегмент: %.1f сек", image_duration)

    if not segments:
        logger.info("Вступление не настроено, пропуск")
        return input_path

    # Основное видео (с fade-in если нужен плавный переход)
    last_transition = image_transition if image_path and image_duration > 0 else gray_transition
    last_fade = image_fade_duration if image_path and image_duration > 0 else gray_fade_duration
    if last_transition == "fade" and last_fade > 0:
        video_prep = os.path.join(temp_dir, "_video_fadein.mp4")
        _apply_fadein(ffmpeg, input_path, video_prep, last_fade)
    else:
        video_prep = input_path

    segments.append(video_prep)

    # Конкатенация
    result = _concat_segments(ffmpeg, segments, output_path, temp_dir)
    logger.info("Вступление готово: %s", output_path)
    return result
