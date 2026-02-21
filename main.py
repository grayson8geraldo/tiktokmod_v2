#!/usr/bin/env python3
"""
Утилита для глубокой уникализации и многослойной обработки видео.
Точка входа — CLI-интерфейс.

Использование:
    python main.py input.mp4 output.mp4 [опции]
    python main.py input.mp4 output.mp4 --config preset.json
    python main.py input.mp4 output.mp4 --anchor-category 02_Urban_EU
"""

import argparse
import json
import logging
import os
import sys

from config import (
    PipelineConfig,
    AnchorConfig,
    HookGapConfig,
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

    section_map = {
        "anchor": cfg.anchor,
        "hook_gap": cfg.hook_gap,
        "matryoshka": cfg.matryoshka,
        "flicker": cfg.flicker,
        "digital_dna": cfg.digital_dna,
        "audio": cfg.audio,
    }

    for section_name, section_obj in section_map.items():
        if section_name in data:
            for k, v in data[section_name].items():
                if hasattr(section_obj, k):
                    setattr(section_obj, k, v)

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

    # --- Anchor ---
    if args.anchor_root:
        cfg.anchor.anchors_root = args.anchor_root
    if args.anchor_category:
        cfg.anchor.category = args.anchor_category
    if args.anchor_head_frames is not None:
        cfg.anchor.head_frames = args.anchor_head_frames
    if args.no_anchor_hflip:
        cfg.anchor.random_hflip = False
    if args.anchor_blur is not None:
        cfg.anchor.background_blur = args.anchor_blur

    # --- Hook Gap ---
    if args.hook_gap_duration is not None:
        cfg.hook_gap.duration = args.hook_gap_duration
    if args.hook_gap_noise is not None:
        cfg.hook_gap.noise_strength = args.hook_gap_noise

    # --- Matryoshka ---
    if args.scale is not None:
        cfg.matryoshka.video_scale = args.scale
    if args.noise_opacity is not None:
        cfg.matryoshka.noise_opacity = args.noise_opacity
    if args.shadow_strength is not None:
        cfg.matryoshka.shadow_strength = args.shadow_strength

    # --- Flicker ---
    if args.no_flicker:
        cfg.flicker.transparency = 0.0
    if args.flicker_transparency is not None:
        cfg.flicker.transparency = args.flicker_transparency

    # --- Digital DNA ---
    if args.no_dna:
        cfg.digital_dna.enabled = False
    if args.flip:
        cfg.digital_dna.horizontal_flip = True
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

  # С выбором категории якоря
  python main.py input.mp4 output.mp4 --anchor-category 02_Urban_EU

  # Без мерцания и с горизонтальным флипом
  python main.py input.mp4 output.mp4 --no-flicker --flip

  # Загрузка настроек из JSON
  python main.py input.mp4 output.mp4 --config my_preset.json
        """,
    )

    parser.add_argument("input", nargs="?", help="Входной видеофайл")
    parser.add_argument("output", nargs="?", help="Выходной видеофайл")
    parser.add_argument("--config", "-c", help="JSON-файл конфигурации")
    parser.add_argument("--save-config", help="Сохранить конфиг по умолчанию в JSON и выйти")
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод")

    # Anchor
    an = parser.add_argument_group("Модуль: Якорь")
    an.add_argument("--anchor-root", help="Корневая папка с якорями")
    an.add_argument("--anchor-category", help="Категория якоря (подпапка)")
    an.add_argument("--anchor-head-frames", type=int, help="Кадров якоря в начале (10-12)")
    an.add_argument("--no-anchor-hflip", action="store_true", help="Отключить случайный hflip якоря")
    an.add_argument("--anchor-blur", type=int, help="Размытие подложки (пиксели)")

    # Hook Gap
    hg = parser.add_argument_group("Модуль: Hook Gap")
    hg.add_argument("--hook-gap-duration", type=float, help="Длительность Hook Gap (0.3-0.6с)")
    hg.add_argument("--hook-gap-noise", type=int, help="Сила шума Hook Gap (0-20)")

    # Matryoshka
    mt = parser.add_argument_group("Модуль: Матрёшка")
    mt.add_argument("--scale", type=float, help="Масштаб видео (0.94–0.97)")
    mt.add_argument("--noise-opacity", type=float, help="Прозрачность шума (0.01–0.03)")
    mt.add_argument("--shadow-strength", type=int, help="Сила тени (0-10)")

    # Flicker
    fl = parser.add_argument_group("Модуль: Мерцание")
    fl.add_argument("--no-flicker", action="store_true", help="Отключить мерцание")
    fl.add_argument("--flicker-transparency", type=float, help="Прозрачность при пропуске (0.0-1.0)")

    # Digital DNA
    dd = parser.add_argument_group("Модуль: Цифровое ДНК")
    dd.add_argument("--no-dna", action="store_true", help="Отключить цифровое ДНК")
    dd.add_argument("--flip", action="store_true", help="Горизонтальный флип")
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
