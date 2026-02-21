"""
Главный пайплайн обработки видео.

Поток:
  1. Подготовка якоря (выбор, вырезка головы, подложки, аудио)
  2. Hook Gap (серый шум 0.3-0.6с + pink noise)
  3. Голова якоря на весь экран (10 кадров = 0.3с)
  4. Матрёшка (видео-подложка + видео 95-97% + мерцание Видео/Подложка + drop shadow + шум)
  5. Конкатенация: Hook Gap → Голова якоря → Матрёшка (с аудио якоря)
  6. Аудио-обработка
  7. Цифровое ДНК (финал)
"""

import logging
import os
import shutil

from config import PipelineConfig
from modules import utils
from modules import anchor_manager
from modules import hook_gap
from modules import matryoshka
from modules import digital_dna
from modules import audio

logger = logging.getLogger(__name__)


def _concat_segments(
    ffmpeg: str,
    segments: list[str],
    output_path: str,
    temp_dir: str,
) -> str:
    """Конкатенирует список видео-сегментов через concat demuxer."""
    concat_list = os.path.join(temp_dir, "_concat_list.txt")
    with open(concat_list, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    utils.run_cmd([
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "конкатенация сегментов")
    return output_path


def _mix_anchor_audio(
    ffmpeg: str,
    video_path: str,
    anchor_audio_path: str,
    output_path: str,
) -> str:
    """
    Микширует аудио якоря (с затуханием) поверх аудио основного видео.

    Аудио якоря плавно затухает за первые N секунд, создавая
    естественный переход от звуков якоря к звукам основного видео.
    """
    filter_complex = (
        f"[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )

    utils.run_cmd([
        ffmpeg, "-y",
        "-i", video_path,
        "-i", anchor_audio_path,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ], "микширование аудио якоря")
    return output_path


def run_pipeline(input_path: str, output_path: str, cfg: PipelineConfig) -> str:
    """Запускает полный пайплайн обработки видео."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Входной файл не найден: {input_path}")

    utils.ensure_dir(cfg.temp_dir)

    ffmpeg = cfg.ffmpeg_path
    ffprobe = cfg.ffprobe_path
    temp = cfg.temp_dir

    info = utils.get_video_info(ffprobe, input_path)
    fps = info["fps"]
    duration = info["duration"]
    out_w = cfg.matryoshka.output_width
    out_h = cfg.matryoshka.output_height

    logger.info(
        "Входное видео: %dx%d, %.1f fps, %.1f сек, аудио: %s",
        info["width"], info["height"], fps,
        duration, "да" if info["has_audio"] else "нет",
    )

    step = 0

    def next_temp(name: str, ext: str = "mp4") -> str:
        nonlocal step
        step += 1
        return os.path.join(temp, f"step{step}_{name}.{ext}")

    # =================================================================
    # Шаг 1: Подготовка якоря
    # =================================================================
    logger.info("=" * 50)
    logger.info("Шаг 1/6: Подготовка якоря")

    anchor_path = anchor_manager.find_anchor(cfg.anchor)

    # Голова якоря (10-12 кадров, уникализированная)
    anchor_head_path = next_temp("anchor_head")
    anchor_manager.prepare_anchor_head(
        anchor_path, anchor_head_path, cfg.anchor,
        ffmpeg=ffmpeg, ffprobe=ffprobe,
        target_w=out_w, target_h=out_h, target_fps=fps,
    )

    # Видео-подложка (зацикленная, размытая)
    bg_video_path = next_temp("anchor_bg")
    anchor_manager.prepare_anchor_background(
        anchor_path, bg_video_path, cfg.anchor,
        ffmpeg=ffmpeg, ffprobe=ffprobe,
        target_w=out_w, target_h=out_h,
        target_fps=fps, target_duration=duration,
    )

    # Аудио якоря (с затуханием)
    anchor_audio_path = next_temp("anchor_audio", ext="m4a")
    anchor_manager.prepare_anchor_audio(
        anchor_path, anchor_audio_path, cfg.anchor,
        ffmpeg=ffmpeg, ffprobe=ffprobe,
        target_duration=duration + cfg.hook_gap.duration + 1.0,
    )

    # =================================================================
    # Шаг 2: Hook Gap (серый шум + pink noise)
    # =================================================================
    logger.info("=" * 50)
    logger.info("Шаг 2/6: Hook Gap (%.2fс)", cfg.hook_gap.duration)

    hook_gap_path = next_temp("hook_gap")
    hook_gap.generate_hook_gap(
        hook_gap_path, cfg.hook_gap,
        ffmpeg=ffmpeg, w=out_w, h=out_h, fps=fps,
    )

    # =================================================================
    # Шаг 3: Матрёшка (подложка-якорь + видео + мерцание + shadow + шум)
    # =================================================================
    logger.info("=" * 50)
    logger.info("Шаг 3/6: Матрёшка + мерцание")

    matryoshka_path = next_temp("matryoshka")
    matryoshka.process(
        input_path, matryoshka_path, cfg.matryoshka,
        ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        background_video=bg_video_path,
        flicker_cfg=cfg.flicker,
    )

    # =================================================================
    # Шаг 4: Конкатенация: Hook Gap → Голова якоря → Матрёшка
    # =================================================================
    logger.info("=" * 50)
    logger.info("Шаг 4/6: Сборка (Hook Gap + Якорь + Видео)")

    concat_path = next_temp("concat")
    segments = [hook_gap_path, anchor_head_path, matryoshka_path]
    _concat_segments(ffmpeg, segments, concat_path, temp)

    # Микшируем аудио якоря поверх конкатенированного видео
    current = next_temp("with_anchor_audio")
    _mix_anchor_audio(ffmpeg, concat_path, anchor_audio_path, current)

    # =================================================================
    # Шаг 5: Аудио-обработка
    # =================================================================
    if cfg.audio.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 5/6: Аудио-обработка")
        out = next_temp("audio")
        current = audio.process(
            current, out, cfg.audio,
            ffmpeg=ffmpeg, ffprobe=ffprobe, temp_dir=temp,
        )

    # =================================================================
    # Шаг 6: Цифровое ДНК
    # =================================================================
    if cfg.digital_dna.enabled:
        logger.info("=" * 50)
        logger.info("Шаг 6/6: Цифровое ДНК")
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
