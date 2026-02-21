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


def _parse_duration(value) -> float:
    """Безопасный парсинг duration — обрабатывает None, 'N/A', '0', пустые строки."""
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s or s.lower() == "n/a":
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


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

    # Длительность — пробуем несколько источников, берём максимальное положительное
    dur_candidates = [
        _parse_duration(video_stream.get("duration")),
        _parse_duration(probe.get("format", {}).get("duration")),
    ]
    # nb_frames / fps как запасной вариант
    nb_frames = _parse_duration(video_stream.get("nb_frames"))
    if nb_frames > 0 and fps > 0:
        dur_candidates.append(nb_frames / fps)

    duration = max(dur_candidates) if dur_candidates else 0.0

    if duration <= 0:
        # Последний fallback: подсчёт кадров через ffprobe
        logger.warning("Не удалось определить длительность из метаданных, "
                       "пробуем count_frames для %s", input_path)
        try:
            result = run_cmd([
                ffprobe_path, "-v", "error",
                "-count_frames",
                "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames",
                "-of", "csv=p=0",
                input_path,
            ], "ffprobe count_frames")
            counted = _parse_duration(result.stdout.strip())
            if counted > 0 and fps > 0:
                duration = counted / fps
        except RuntimeError:
            pass

    # Аудио битрейт
    audio_bitrate = None
    if audio_stream:
        raw_br = audio_stream.get("bit_rate")
        if raw_br and str(raw_br).lower() != "n/a":
            try:
                audio_bitrate = int(raw_br) // 1000  # kbps
            except (ValueError, TypeError):
                audio_bitrate = None

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
