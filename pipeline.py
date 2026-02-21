"""
Главный пайплайн обработки видео.
Последовательно применяет все модули к входному файлу.
"""

import logging
import os
import shutil

from config import PipelineConfig
from modules import utils
from modules import zero_frame
from modules import matryoshka
from modules import flicker
from modules import digital_dna
from modules import audio

logger = logging.getLogger(__name__)


def run_pipeline(input_path: str, output_path: str, cfg: PipelineConfig) -> str:
    """
    Запускает полный пайплайн обработки видео.

    Порядок модулей:
      1. Нулевой кадр (zero_frame)
      2. Визуальная матрёшка (matryoshka)
      3. Кадровое мерцание (flicker)
      4. Аудио-обработка (audio)
      5. Цифровое ДНК (digital_dna) — финальный шаг

    Возвращает путь к итоговому файлу.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Входной файл не найден: {input_path}")

    utils.ensure_dir(cfg.temp_dir)

    ffmpeg = cfg.ffmpeg_path
    ffprobe = cfg.ffprobe_path
    temp = cfg.temp_dir

    # Получаем информацию о видео для логирования
    info = utils.get_video_info(ffprobe, input_path)
    logger.info(
        "Входное видео: %dx%d, %.1f fps, %.1f сек, аудио: %s",
        info["width"], info["height"], info["fps"],
        info["duration"], "да" if info["has_audio"] else "нет",
    )

    current = input_path
    step = 0

    def next_temp(name: str) -> str:
        nonlocal step
        step += 1
        return os.path.join(temp, f"step{step}_{name}.mp4")

    # --- Шаг 1: Нулевой кадр ---
    if cfg.zero_frame.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 1/5: Нулевой кадр")
        out = next_temp("zero_frame")
        current = zero_frame.process(
            current, out, cfg.zero_frame,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )

    # --- Шаг 2: Визуальная матрёшка ---
    if cfg.matryoshka.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 2/5: Визуальная матрёшка")
        out = next_temp("matryoshka")
        current = matryoshka.process(
            current, out, cfg.matryoshka,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )

    # --- Шаг 3: Кадровое мерцание ---
    if cfg.flicker.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 3/5: Кадровое мерцание")
        out = next_temp("flicker")
        current = flicker.process(
            current, out, cfg.flicker,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )

    # --- Шаг 4: Аудио-обработка ---
    if cfg.audio.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 4/5: Аудио-обработка")
        out = next_temp("audio")
        current = audio.process(
            current, out, cfg.audio,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )

    # --- Шаг 5: Цифровое ДНК ---
    if cfg.digital_dna.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 5/5: Цифровое ДНК")
        current = digital_dna.process(
            current, output_path, cfg.digital_dna,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )
    else:
        shutil.copy2(current, output_path)

    logger.info("=" * 50)
    logger.info("Обработка завершена: %s", output_path)

    # Очистка промежуточных файлов
    _cleanup_temp(temp)

    return output_path


def _cleanup_temp(temp_dir: str):
    """Удаление промежуточных файлов."""
    try:
        for f in os.listdir(temp_dir):
            fp = os.path.join(temp_dir, f)
            if os.path.isfile(fp) and f.startswith(("step", "_")):
                os.remove(fp)
                logger.debug("Удалён временный файл: %s", fp)
    except OSError as e:
        logger.warning("Ошибка при очистке temp: %s", e)
