"""
Модуль 4: Уникализация «Цифрового ДНК».
  - Полное удаление исходных EXIF/метаданных
  - Инъекция фейковых метаданных (модель телефона, даты, GPS)
  - Микро-обрезка (удаление 2–5 кадров в конце)
  - Изменение битрейта аудио на ±1–2 кбит/с
  - Опциональный горизонтальный флип
"""

import logging
import os
import random
import subprocess
from datetime import datetime, timedelta

from config import DigitalDNAConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)

# Пул фейковых моделей устройств
FAKE_DEVICES = [
    {"make": "Apple", "model": "iPhone 15 Pro Max"},
    {"make": "Apple", "model": "iPhone 14 Pro"},
    {"make": "Apple", "model": "iPhone 13"},
    {"make": "Apple", "model": "iPhone 16 Pro"},
    {"make": "Samsung", "model": "Galaxy S24 Ultra"},
    {"make": "Samsung", "model": "Galaxy S23+"},
    {"make": "Samsung", "model": "Galaxy A54"},
    {"make": "Samsung", "model": "Galaxy Z Flip5"},
    {"make": "Apple", "model": "iPhone 15"},
    {"make": "Samsung", "model": "Galaxy S24"},
]


def _generate_fake_metadata() -> dict:
    """Генерирует набор фейковых метаданных."""
    device = random.choice(FAKE_DEVICES)

    # Случайная дата съёмки (последние 90 дней)
    days_ago = random.randint(1, 90)
    fake_date = datetime.now() - timedelta(days=days_ago)
    date_str = fake_date.strftime("%Y:%m:%d %H:%M:%S")

    # Фейковые GPS-координаты (разные города мира)
    gps_locations = [
        (40.7128, -74.0060),    # New York
        (34.0522, -118.2437),   # Los Angeles
        (51.5074, -0.1278),     # London
        (48.8566, 2.3522),      # Paris
        (35.6762, 139.6503),    # Tokyo
        (55.7558, 37.6173),     # Moscow
        (37.5665, 126.9780),    # Seoul
        (-33.8688, 151.2093),   # Sydney
        (52.5200, 13.4050),     # Berlin
        (41.9028, 12.4964),     # Rome
    ]
    lat, lon = random.choice(gps_locations)
    # Добавляем микро-смещение
    lat += random.uniform(-0.01, 0.01)
    lon += random.uniform(-0.01, 0.01)

    return {
        "make": device["make"],
        "model": device["model"],
        "date": date_str,
        "gps_lat": lat,
        "gps_lon": lon,
    }


def _strip_and_inject_metadata_ffmpeg(
    ffmpeg: str, input_path: str, output_path: str, fake_meta: dict,
):
    """
    Удаляет все метаданные и вставляет фейковые через FFmpeg.
    Используется когда ExifTool недоступен.
    """
    gps_lat = fake_meta["gps_lat"]
    gps_lon = fake_meta["gps_lon"]
    lat_ref = "N" if gps_lat >= 0 else "S"
    lon_ref = "E" if gps_lon >= 0 else "W"

    run_cmd([
        ffmpeg, "-y",
        "-i", input_path,
        "-map_metadata", "-1",  # удаляем все метаданные
        "-metadata", f"make={fake_meta['make']}",
        "-metadata", f"model={fake_meta['model']}",
        "-metadata", f"creation_time={fake_meta['date'].replace(':', '-', 2)}",
        "-metadata", f"com.apple.quicktime.make={fake_meta['make']}",
        "-metadata", f"com.apple.quicktime.model={fake_meta['model']}",
        "-metadata", f"location={gps_lat:+.4f}{gps_lon:+.4f}/",
        "-c:v", "copy",
        "-c:a", "copy",
        output_path,
    ], "очистка и инъекция метаданных (ffmpeg)")


def _try_exiftool(input_path: str, fake_meta: dict) -> bool:
    """Попытка использовать ExifTool для более глубокой инъекции метаданных."""
    try:
        subprocess.run(["exiftool", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        logger.info("ExifTool не найден, используем FFmpeg для метаданных")
        return False

    gps_lat = abs(fake_meta["gps_lat"])
    gps_lon = abs(fake_meta["gps_lon"])
    lat_ref = "N" if fake_meta["gps_lat"] >= 0 else "S"
    lon_ref = "E" if fake_meta["gps_lon"] >= 0 else "W"

    run_cmd([
        "exiftool",
        "-overwrite_original",
        "-all=",  # удалить всё
        f"-Make={fake_meta['make']}",
        f"-Model={fake_meta['model']}",
        f"-DateTimeOriginal={fake_meta['date']}",
        f"-CreateDate={fake_meta['date']}",
        f"-GPSLatitude={gps_lat}",
        f"-GPSLatitudeRef={lat_ref}",
        f"-GPSLongitude={gps_lon}",
        f"-GPSLongitudeRef={lon_ref}",
        input_path,
    ], "ExifTool инъекция метаданных")
    return True


def process(
    input_path: str,
    output_path: str,
    cfg: DigitalDNAConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Выполняет уникализацию «Цифрового ДНК».
    """
    if not cfg.enabled:
        logger.info("Модуль DigitalDNA отключён, пропуск")
        return input_path

    info = get_video_info(ffprobe, input_path)
    fps = info["fps"]
    duration = info["duration"]

    current_input = input_path
    step_output = os.path.join(temp_dir, "_dna_step1.mp4")

    # --- 1. Микро-обрезка (удаление 2–5 кадров с конца) ---
    trim_frames = random.randint(cfg.trim_tail_frames_min, cfg.trim_tail_frames_max)
    trim_duration = trim_frames / fps
    new_duration = max(duration - trim_duration, 1.0)  # не менее 1 сек

    logger.info("Микро-обрезка: удаляем %d кадров (%.3f сек) с конца", trim_frames, trim_duration)

    vf_filters = []

    # --- 2. Горизонтальный флип (если включён) ---
    if cfg.horizontal_flip:
        vf_filters.append("hflip")

    vf_str = ",".join(vf_filters) if vf_filters else None

    cmd = [
        ffmpeg, "-y",
        "-i", current_input,
        "-t", str(new_duration),
    ]
    if vf_str:
        cmd.extend(["-vf", vf_str])

    # --- 3. Изменение битрейта аудио ---
    if info["has_audio"] and info["audio_bitrate_kbps"]:
        shift = random.choice([-1, 1]) * cfg.audio_bitrate_shift_kbps
        new_audio_br = max(info["audio_bitrate_kbps"] + shift, 32)
        cmd.extend(["-c:v", "libx264", "-preset", "fast"])
        cmd.extend(["-c:a", "aac", "-b:a", f"{new_audio_br}k"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "fast"])
        cmd.extend(["-c:a", "copy"])

    cmd.extend(["-pix_fmt", "yuv420p", step_output])
    run_cmd(cmd, "микро-обрезка + флип + битрейт аудио")

    current_input = step_output

    # --- 4. Очистка/инъекция метаданных ---
    if cfg.strip_metadata or cfg.inject_fake_metadata:
        fake_meta = _generate_fake_metadata() if cfg.inject_fake_metadata else {}

        if cfg.inject_fake_metadata:
            logger.info(
                "Фейковые метаданные: %s %s, дата %s, GPS (%.4f, %.4f)",
                fake_meta["make"], fake_meta["model"],
                fake_meta["date"],
                fake_meta["gps_lat"], fake_meta["gps_lon"],
            )

        # Сначала пробуем ExifTool
        if cfg.inject_fake_metadata and _try_exiftool(current_input, fake_meta):
            # ExifTool сработал, копируем результат
            import shutil
            shutil.copy2(current_input, output_path)
        else:
            # Fallback на FFmpeg
            if cfg.inject_fake_metadata:
                _strip_and_inject_metadata_ffmpeg(
                    ffmpeg, current_input, output_path, fake_meta
                )
            else:
                # Только удаление метаданных
                run_cmd([
                    ffmpeg, "-y",
                    "-i", current_input,
                    "-map_metadata", "-1",
                    "-c:v", "copy", "-c:a", "copy",
                    output_path,
                ], "удаление метаданных")
    else:
        import shutil
        shutil.copy2(current_input, output_path)

    logger.info("Цифровое ДНК обработано: %s", output_path)
    return output_path
