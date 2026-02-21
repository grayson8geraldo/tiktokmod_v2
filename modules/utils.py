"""
Общие утилиты: получение информации о видео, запуск FFmpeg и т.д.
"""

import json
import os
import subprocess
import logging

logger = logging.getLogger(__name__)


def run_cmd(cmd: list[str], description: str = "") -> subprocess.CompletedProcess:
    """Запуск команды с логированием."""
    logger.info("Запуск: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Ошибка при '%s': %s", description or cmd[0], result.stderr)
        raise RuntimeError(
            f"Команда завершилась с ошибкой (код {result.returncode}): "
            f"{result.stderr[:500]}"
        )
    return result


def probe_video(ffprobe_path: str, input_path: str) -> dict:
    """Получить метаинформацию о видеофайле через ffprobe."""
    cmd = [
        ffprobe_path, "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        input_path,
    ]
    result = run_cmd(cmd, "ffprobe")
    return json.loads(result.stdout)


def get_video_info(ffprobe_path: str, input_path: str) -> dict:
    """Извлечь основные параметры видео: ширина, высота, fps, длительность, кодек аудио."""
    probe = probe_video(ffprobe_path, input_path)

    video_stream = None
    audio_stream = None
    for s in probe.get("streams", []):
        if s["codec_type"] == "video" and video_stream is None:
            video_stream = s
        elif s["codec_type"] == "audio" and audio_stream is None:
            audio_stream = s

    if video_stream is None:
        raise ValueError(f"В файле {input_path} не найден видеопоток")

    # FPS
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    num, den = map(int, r_frame_rate.split("/"))
    fps = num / den if den else 30.0

    # Длительность
    duration = float(
        video_stream.get("duration")
        or probe.get("format", {}).get("duration", "0")
    )

    # Аудио битрейт
    audio_bitrate = None
    if audio_stream:
        audio_bitrate = int(audio_stream.get("bit_rate", 0)) // 1000  # kbps

    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "fps": fps,
        "duration": duration,
        "total_frames": int(duration * fps),
        "has_audio": audio_stream is not None,
        "audio_bitrate_kbps": audio_bitrate,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
    }


def ensure_dir(path: str):
    """Создать директорию, если она не существует."""
    os.makedirs(path, exist_ok=True)
