"""
Модуль 3: Кадровое мерцание (Interleaving).
Реализация алгоритма прерывания видеопотока чёрными кадрами:
  - Чередование: [Видео: 1 кадр] -> [Чёрный: 1 кадр]
  - Сдвиг фазы: каждые N секунд — 3 последовательных чёрных кадра
"""

import logging

from config import FlickerConfig
from modules.utils import run_cmd, get_video_info

logger = logging.getLogger(__name__)


def process(
    input_path: str,
    output_path: str,
    cfg: FlickerConfig,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    temp_dir: str = "/tmp/videomod_temp",
) -> str:
    """
    Применяет кадровое мерцание к видео.
    """
    if not cfg.enabled:
        logger.info("Модуль Flicker отключён, пропуск")
        return input_path

    info = get_video_info(ffprobe, input_path)
    fps = info["fps"]
    w, h = info["width"], info["height"]

    phase_interval_frames = int(fps * cfg.phase_shift_interval)
    black_burst = cfg.phase_shift_black_frames

    # Стратегия: drawbox с компактным enable-выражением.
    #
    # Кадр n зачерняется если:
    #   1) mod(n, interleave_every) >= 1  — чередование (каждый 2-й кадр чёрный)
    #   2) mod(n, phase_interval) < black_burst  — пачка чёрных кадров
    #      каждые phase_interval кадров (сдвиг фазы)
    #
    # Используем одну формулу с mod() вместо перечисления сотен between().
    # gt(x, 0) = true когда хотя бы одно условие сработало.

    interleave = cfg.interleave_every

    # Условие 1: чередование — mod(n, interleave) >= 1
    cond_interleave = f"gte(mod(n\\,{interleave})\\,1)"

    # Условие 2: пауза — mod(n, interval) < burst
    cond_pause = f"lt(mod(n\\,{phase_interval_frames})\\,{black_burst})"

    # Объединяем: чернить если ЛЮБОЕ условие истинно
    enable_expr = f"'{cond_interleave}+{cond_pause}'"

    filter_str = (
        f"drawbox=x=0:y=0:w={w}:h={h}:color=black@1:t=fill:"
        f"enable={enable_expr}"
    )

    logger.info(
        "Мерцание: interleave=%d, phase_interval=%d кадров, burst=%d",
        interleave, phase_interval_frames, black_burst,
    )

    run_cmd([
        ffmpeg, "-y",
        "-i", input_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "кадровое мерцание")

    logger.info("Мерцание применено: %s", output_path)
    return output_path
