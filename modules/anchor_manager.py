"""
Модуль: Управление библиотекой «якорей» (Anchor Manager).

Функции:
  1. Выбор случайного якоря из нужной категории.
  2. Вырезка случайного фрагмента 10-12 кадров для «головы».
  3. Уникализация: hflip (50%), микро-коррекция экспозиции, цветовой сдвиг,
     ISO grain, переименование в формат мобильной камеры.
  4. Подготовка подложки: размытие (BoxBlur/Gaussian), зацикливание/замедление.
  5. Склейка аудио якоря с плавным затуханием.
"""

import logging
import os
import random
from datetime import datetime

from config import AnchorConfig
from modules.utils import run_cmd, get_video_info, ensure_dir

logger = logging.getLogger(__name__)

# Паттерны именования «камерой»
_CAMERA_NAME_PATTERNS = [
    "DCIM_{:04d}.mp4",
    "IMG_{:04d}.mp4",
    "VID_{date}_{:04d}.mp4",
    "MOV_{:04d}.mp4",
]


def _pick_camera_name() -> str:
    """Генерирует имя файла в стиле мобильной камеры."""
    pattern = random.choice(_CAMERA_NAME_PATTERNS)
    num = random.randint(1, 9999)
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    return pattern.format(num, date=date_str)


def find_anchor(cfg: AnchorConfig) -> str:
    """
    Выбирает случайный видеофайл из библиотеки якорей.

    Если category задана — ищет в конкретной подпапке.
    Если нет — берёт из любой.
    """
    root = cfg.anchors_root
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Папка якорей не найдена: {root}")

    video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    candidates = []

    if cfg.category:
        search_dir = os.path.join(root, cfg.category)
        if not os.path.isdir(search_dir):
            raise FileNotFoundError(
                f"Категория якорей не найдена: {search_dir}"
            )
        dirs = [search_dir]
    else:
        dirs = [
            os.path.join(root, d) for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d))
        ]

    for d in dirs:
        for f in os.listdir(d):
            if os.path.splitext(f)[1].lower() in video_exts:
                candidates.append(os.path.join(d, f))

    if not candidates:
        raise FileNotFoundError(
            f"В библиотеке якорей нет видеофайлов: {root}"
        )

    chosen = random.choice(candidates)
    logger.info("Выбран якорь: %s", chosen)
    return chosen


def prepare_anchor_head(
    anchor_path: str,
    output_path: str,
    cfg: AnchorConfig,
    ffmpeg: str,
    ffprobe: str,
    target_w: int,
    target_h: int,
    target_fps: float,
) -> str:
    """
    Вырезает случайный фрагмент 10-12 кадров из якоря и уникализирует.

    Применяет:
      - Случайная точка старта
      - hflip с вероятностью 50%
      - Микро-коррекция экспозиции (±1%)
      - Цветовой сдвиг (±1.5%)
      - ISO grain (шум)
      - Масштабирование под целевое разрешение
    """
    info = get_video_info(ffprobe, anchor_path)
    anchor_fps = info["fps"]
    anchor_duration = info["duration"]
    anchor_frames = info["total_frames"]

    # Сколько кадров вырезать
    head_frames = cfg.head_frames + random.randint(0, 2)  # 10-12
    head_duration = head_frames / anchor_fps

    # Случайная точка старта (не ближе чем head_duration от конца)
    max_start = max(0, anchor_duration - head_duration - 0.5)
    start_time = random.uniform(0, max_start) if max_start > 0 else 0

    logger.info(
        "Голова якоря: %d кадров (%.2fс) с позиции %.2fс",
        head_frames, head_duration, start_time,
    )

    # --- Фильтры уникализации ---
    vf_parts = []

    # Масштаб под целевое разрешение
    vf_parts.append(
        f"scale={target_w}:{target_h}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}"
    )

    # hflip с вероятностью 50%
    if cfg.random_hflip and random.random() < 0.5:
        vf_parts.append("hflip")
        logger.info("  hflip: да")

    # Микро-коррекция экспозиции (eq filter: brightness ±0.01)
    exposure_shift = random.uniform(
        -cfg.exposure_shift_pct / 100,
        cfg.exposure_shift_pct / 100,
    )
    # eq brightness range: -1.0 to 1.0
    vf_parts.append(f"eq=brightness={exposure_shift:.4f}")

    # Цветовой сдвиг (hue rotate ±1-2 градуса)
    hue_shift = random.uniform(-cfg.color_shift_pct * 2, cfg.color_shift_pct * 2)
    vf_parts.append(f"hue=h={hue_shift:.2f}")

    # ISO grain (шум)
    if cfg.iso_grain_strength > 0:
        vf_parts.append(f"noise=c0s={cfg.iso_grain_strength}:allf=t")

    # Установка FPS под целевое видео
    vf_parts.append(f"fps={target_fps}")

    vf_str = ",".join(vf_parts)

    cmd = [
        ffmpeg, "-y",
        "-ss", str(start_time),
        "-i", anchor_path,
        "-t", str(head_duration),
        "-vf", vf_str,
        "-an",  # без аудио для головы
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    run_cmd(cmd, "подготовка головы якоря")

    logger.info("Голова якоря готова: %s", output_path)
    return output_path


def prepare_anchor_background(
    anchor_path: str,
    output_path: str,
    cfg: AnchorConfig,
    ffmpeg: str,
    ffprobe: str,
    target_w: int,
    target_h: int,
    target_fps: float,
    target_duration: float,
) -> str:
    """
    Готовит видео-подложку из якоря.

    Тот же файл, из которого взят якорь, зацикливается или замедляется
    до нужной длительности. Применяется BoxBlur и уникализация.
    """
    info = get_video_info(ffprobe, anchor_path)

    vf_parts = []

    # Масштаб и кроп
    vf_parts.append(
        f"scale={target_w}:{target_h}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}"
    )

    # Размытие подложки (BoxBlur)
    if cfg.background_blur > 0:
        # boxblur принимает luma_radius:luma_power
        vf_parts.append(f"boxblur={cfg.background_blur}:{cfg.background_blur}")

    # ISO grain
    if cfg.iso_grain_strength > 0:
        vf_parts.append(f"noise=c0s={cfg.iso_grain_strength}:allf=t")

    # Установка FPS
    vf_parts.append(f"fps={target_fps}")

    vf_str = ",".join(vf_parts)

    # Зацикливание: используем -stream_loop для повтора якоря
    # если якорь короче целевой длительности
    anchor_duration = info["duration"]
    loops_needed = int(target_duration / anchor_duration) + 1 if anchor_duration > 0 else 0

    cmd = [
        ffmpeg, "-y",
        "-stream_loop", str(loops_needed),
        "-i", anchor_path,
        "-t", str(target_duration),
        "-vf", vf_str,
        "-an",  # аудио подложки обрабатывается отдельно
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    run_cmd(cmd, "подготовка видео-подложки")

    logger.info(
        "Подложка готова: %dx%d, %.1fс, blur=%d: %s",
        target_w, target_h, target_duration, cfg.background_blur, output_path,
    )
    return output_path


def prepare_anchor_audio(
    anchor_path: str,
    output_path: str,
    cfg: AnchorConfig,
    ffmpeg: str,
    ffprobe: str,
    target_duration: float,
) -> str:
    """
    Извлекает аудио из якоря и подготавливает с плавным затуханием.

    Аудио якоря (шум города, пение птиц, звук шагов) не обрывается резко,
    а плавно затухает на протяжении первых 2-3 секунд основного видео.
    """
    info = get_video_info(ffprobe, anchor_path)

    if not info["has_audio"]:
        logger.info("Якорь не имеет аудиодорожки, генерируем тишину")
        # Генерируем тихий pink noise как замену
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"anoisesrc=sample_rate=44100:color=pink:d={target_duration}",
            "-af", "volume=-50dB",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
        run_cmd(cmd, "генерация фонового аудио якоря")
        return output_path

    # Зацикливаем аудио до нужной длительности
    anchor_duration = info["duration"]
    loops_needed = int(target_duration / anchor_duration) + 1 if anchor_duration > 0 else 0

    # Затухание: громко в начале, затухает за audio_fade_duration секунд
    fade_dur = cfg.audio_fade_duration
    # afade: плавное затухание начиная с 0 секунды, длительностью fade_dur
    af_parts = [f"afade=t=out:st=0:d={fade_dur}"]

    cmd = [
        ffmpeg, "-y",
        "-stream_loop", str(loops_needed),
        "-i", anchor_path,
        "-t", str(target_duration),
        "-vn",  # только аудио
        "-af", ",".join(af_parts),
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    run_cmd(cmd, "подготовка аудио якоря с затуханием")

    logger.info(
        "Аудио якоря: %.1fс, затухание %.1fс: %s",
        target_duration, fade_dur, output_path,
    )
    return output_path
