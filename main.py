#!/usr/bin/env python3
"""
Утилита для глубокой уникализации и многослойной обработки видео.
Точка входа — CLI-интерфейс.

Использование:
    python main.py input.mp4 output.mp4 [опции]
    python main.py input.mp4 output.mp4 --config preset.json
    python main.py input.mp4 output.mp4 --no-flicker --no-audio --flip
"""

import argparse
import json
import logging
import os
import sys

from config import (
    PipelineConfig,
    ZeroFrameConfig,
    MatryoshkaConfig,
    FlickerConfig,
    DigitalDNAConfig,
    AudioConfig,
)
from pipeline import run_pipeline


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config_from_json(path: str) -> PipelineConfig:
    """Загрузка конфигурации из JSON-файла."""
    with open(path) as f:
        data = json.load(f)

    cfg = PipelineConfig()

    if "zero_frame" in data:
        for k, v in data["zero_frame"].items():
            if hasattr(cfg.zero_frame, k):
                setattr(cfg.zero_frame, k, v)

    if "matryoshka" in data:
        for k, v in data["matryoshka"].items():
            if hasattr(cfg.matryoshka, k):
                setattr(cfg.matryoshka, k, v)

    if "flicker" in data:
        for k, v in data["flicker"].items():
            if hasattr(cfg.flicker, k):
                setattr(cfg.flicker, k, v)

    if "digital_dna" in data:
        for k, v in data["digital_dna"].items():
            if hasattr(cfg.digital_dna, k):
                setattr(cfg.digital_dna, k, v)

    if "audio" in data:
        for k, v in data["audio"].items():
            if hasattr(cfg.audio, k):
                setattr(cfg.audio, k, v)

    for k in ("temp_dir", "ffmpeg_path", "ffprobe_path"):
        if k in data:
            setattr(cfg, k, data[k])

    return cfg


def build_config_from_args(args: argparse.Namespace) -> PipelineConfig:
    """Построение конфигурации из аргументов CLI."""
    if args.config:
        cfg = load_config_from_json(args.config)
    else:
        cfg = PipelineConfig()

    # --- Zero Frame ---
    if args.no_zero_frame:
        cfg.zero_frame.enabled = False
    if args.zero_frame_mode:
        cfg.zero_frame.mode = args.zero_frame_mode
    if args.zero_frame_image:
        cfg.zero_frame.mode = "image"
        cfg.zero_frame.image_path = args.zero_frame_image
    if args.zero_frame_duration is not None:
        cfg.zero_frame.duration = args.zero_frame_duration
    if args.zero_frame_transition:
        cfg.zero_frame.transition = args.zero_frame_transition

    # --- Matryoshka ---
    if args.no_matryoshka:
        cfg.matryoshka.enabled = False
    if args.background:
        cfg.matryoshka.background_image = args.background
    if args.scale is not None:
        cfg.matryoshka.video_scale = args.scale
    if args.noise_opacity is not None:
        cfg.matryoshka.noise_opacity = args.noise_opacity

    # --- Flicker ---
    if args.no_flicker:
        cfg.flicker.enabled = False
    if args.phase_interval is not None:
        cfg.flicker.phase_shift_interval = args.phase_interval

    # --- Digital DNA ---
    if args.no_dna:
        cfg.digital_dna.enabled = False
    if args.flip:
        cfg.digital_dna.horizontal_flip = True
    if args.no_flip:
        cfg.digital_dna.horizontal_flip = False
    if args.no_fake_meta:
        cfg.digital_dna.inject_fake_metadata = False

    # --- Audio ---
    if args.no_audio:
        cfg.audio.enabled = False
    if args.pitch is not None:
        cfg.audio.pitch_shift_semitones = args.pitch
    if args.pitch_direction:
        cfg.audio.pitch_direction = args.pitch_direction
    if args.pink_noise_db is not None:
        cfg.audio.pink_noise_volume_db = args.pink_noise_db

    # --- Общие ---
    if args.temp_dir:
        cfg.temp_dir = args.temp_dir
    if args.ffmpeg:
        cfg.ffmpeg_path = args.ffmpeg
    if args.ffprobe:
        cfg.ffprobe_path = args.ffprobe

    return cfg


def save_default_config(path: str):
    """Сохраняет конфигурацию по умолчанию в JSON."""
    from dataclasses import asdict
    cfg = PipelineConfig()
    with open(path, "w") as f:
        json.dump(asdict(cfg), f, indent=2, ensure_ascii=False)
    print(f"Конфигурация по умолчанию сохранена в: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Утилита для глубокой уникализации и многослойной обработки видео",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Полная обработка со всеми модулями
  python main.py input.mp4 output.mp4

  # Без мерцания и с горизонтальным флипом
  python main.py input.mp4 output.mp4 --no-flicker --flip

  # С пользовательским фоном и изображением нулевого кадра
  python main.py input.mp4 output.mp4 --background bg.jpg --zero-frame-image intro.png

  # Загрузка настроек из JSON
  python main.py input.mp4 output.mp4 --config my_preset.json

  # Сохранить конфиг по умолчанию
  python main.py --save-config default_config.json
        """,
    )

    parser.add_argument("input", nargs="?", help="Входной видеофайл")
    parser.add_argument("output", nargs="?", help="Выходной видеофайл")
    parser.add_argument("--config", "-c", help="JSON-файл конфигурации")
    parser.add_argument("--save-config", help="Сохранить конфиг по умолчанию в JSON и выйти")
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод")

    # Zero Frame
    zf = parser.add_argument_group("Модуль: Нулевой кадр")
    zf.add_argument("--no-zero-frame", action="store_true", help="Отключить нулевой кадр")
    zf.add_argument("--zero-frame-mode", choices=["gray", "image"], help="Тип нулевого кадра")
    zf.add_argument("--zero-frame-image", help="Изображение для нулевого кадра")
    zf.add_argument("--zero-frame-duration", type=float, help="Длительность (0.1–1.5 сек)")
    zf.add_argument("--zero-frame-transition", choices=["fade", "cut"], help="Тип перехода")

    # Matryoshka
    mt = parser.add_argument_group("Модуль: Матрёшка")
    mt.add_argument("--no-matryoshka", action="store_true", help="Отключить матрёшку")
    mt.add_argument("--background", "-bg", help="Фоновое изображение-подложка")
    mt.add_argument("--scale", type=float, help="Масштаб видео (0.95–0.98)")
    mt.add_argument("--noise-opacity", type=float, help="Прозрачность шума (0.01–0.03)")

    # Flicker
    fl = parser.add_argument_group("Модуль: Мерцание")
    fl.add_argument("--no-flicker", action="store_true", help="Отключить мерцание")
    fl.add_argument("--phase-interval", type=float, help="Интервал сдвига фазы (сек)")

    # Digital DNA
    dd = parser.add_argument_group("Модуль: Цифровое ДНК")
    dd.add_argument("--no-dna", action="store_true", help="Отключить цифровое ДНК")
    dd.add_argument("--flip", action="store_true", help="Горизонтальный флип")
    dd.add_argument("--no-flip", action="store_true", help="Отключить горизонтальный флип")
    dd.add_argument("--no-fake-meta", action="store_true", help="Не вставлять фейковые метаданные")

    # Audio
    au = parser.add_argument_group("Модуль: Аудио")
    au.add_argument("--no-audio", action="store_true", help="Отключить аудио-обработку")
    au.add_argument("--pitch", type=float, help="Pitch shift в полутонах (0.1–0.3)")
    au.add_argument("--pitch-direction", choices=["up", "down", "random"], help="Направление pitch")
    au.add_argument("--pink-noise-db", type=float, help="Громкость розового шума (дБ, напр. -45)")

    # Общие
    gen = parser.add_argument_group("Общие")
    gen.add_argument("--temp-dir", help="Директория для временных файлов")
    gen.add_argument("--ffmpeg", help="Путь к FFmpeg")
    gen.add_argument("--ffprobe", help="Путь к FFprobe")

    args = parser.parse_args()

    # Сохранение конфига
    if args.save_config:
        save_default_config(args.save_config)
        return

    # Проверка обязательных аргументов
    if not args.input or not args.output:
        parser.error("Требуются аргументы: input и output")

    if not os.path.isfile(args.input):
        parser.error(f"Входной файл не найден: {args.input}")

    setup_logging(args.verbose)
    logger = logging.getLogger("main")

    cfg = build_config_from_args(args)

    logger.info("Запуск обработки: %s -> %s", args.input, args.output)

    try:
        result = run_pipeline(
            os.path.abspath(args.input),
            os.path.abspath(args.output),
            cfg,
        )
        logger.info("Готово! Результат: %s", result)
        print(f"\nГотово: {result}")
    except Exception as e:
        logger.error("Ошибка обработки: %s", e, exc_info=True)
        print(f"\nОшибка: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
