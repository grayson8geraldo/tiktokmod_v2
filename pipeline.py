"""
Главный пайплайн обработки видео.

Три режима (preset):
  gray_image_flicker — серый(0.3с) + картинка(0.7с) → подложка + видео с мерцанием
  gray_flicker       — серый(1с) → видео с мерцанием (без подложки)
  image_video        — картинка(0.3-1с) → подложка + видео (без мерцания)

Порядок:
  1. Вступление (zero_frame — серый/картинка сегменты)
  2. Матрёшка (подложка + видео + шум, опционально с мерцанием внутри)
  3. Аудио-обработка
  4. Цифровое ДНК (финал)
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
    """Запускает полный пайплайн обработки видео."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Входной файл не найден: {input_path}")

    utils.ensure_dir(cfg.temp_dir)

    ffmpeg = cfg.ffmpeg_path
    ffprobe = cfg.ffprobe_path
    temp = cfg.temp_dir
    preset = cfg.preset

    info = utils.get_video_info(ffprobe, input_path)
    logger.info(
        "Входное видео: %dx%d, %.1f fps, %.1f сек, аудио: %s",
        info["width"], info["height"], info["fps"],
        info["duration"], "да" if info["has_audio"] else "нет",
    )
    logger.info("Режим: %s", preset)

    current = input_path
    step = 0

    def next_temp(name: str) -> str:
        nonlocal step
        step += 1
        return os.path.join(temp, f"step{step}_{name}.mp4")

    # --- Определяем параметры по режиму ---
    use_gray = preset in ("gray_image_flicker", "gray_flicker")
    use_image_intro = preset in ("gray_image_flicker", "image_video")
    use_flicker = preset in ("gray_image_flicker", "gray_flicker")
    use_background = preset in ("gray_image_flicker", "image_video")

    # --- Шаг 1: Вступление ---
    gray_dur = 0.0
    image_intro_dur = 0.0

    if use_gray:
        gray_dur = cfg.zero_frame.gray_duration
    if use_image_intro and cfg.image_intro.image_path:
        image_intro_dur = cfg.image_intro.duration

    if gray_dur > 0 or image_intro_dur > 0:
        logger.info("=" * 50)
        logger.info("Шаг 1/4: Вступление")
        out = next_temp("intro")
        current = zero_frame.build_intro(
            current, out,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
            gray_duration=gray_dur,
            gray_transition=cfg.zero_frame.transition,
            gray_fade_duration=cfg.zero_frame.fade_duration,
            image_path=cfg.image_intro.image_path if use_image_intro else None,
            image_duration=image_intro_dur,
            image_transition=cfg.image_intro.transition,
            image_fade_duration=cfg.image_intro.fade_duration,
        )

    # --- Шаг 2: Матрёшка + мерцание ---
    logger.info("=" * 50)
    logger.info("Шаг 2/4: Матрёшка%s", " + мерцание" if use_flicker else "")
    out = next_temp("matryoshka")

    bg_image = None
    if use_background and cfg.image_intro.image_path:
        bg_image = cfg.image_intro.image_path

    current = matryoshka.process(
        current, out, cfg.matryoshka,
        ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        background_image=bg_image,
        flicker_cfg=cfg.flicker if use_flicker else None,
    )

    # --- Шаг 3: Аудио ---
    if cfg.audio.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 3/4: Аудио-обработка")
        out = next_temp("audio")
        current = audio.process(
            current, out, cfg.audio,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )

    # --- Шаг 4: Цифровое ДНК ---
    if cfg.digital_dna.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 4/4: Цифровое ДНК")
        current = digital_dna.process(
            current, output_path, cfg.digital_dna,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )
    else:
        shutil.copy2(current, output_path)

    logger.info("=" * 50)
    logger.info("Обработка завершена: %s", output_path)

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
