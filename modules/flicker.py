"""
Модуль В: Адаптивное мерцание (Soft Interleaving).

Принципиальные отличия:
  1. Вместо Видео/Чёрный — Видео/Подложка.
     Когда наступает фаза «пропуска», основное видео становится прозрачным
     на 85%, обнажая подложку под ним.

  2. Рандомизация «пропусков»:
     Интервал между пропусками: случайный (1.5–2.5 сек).
     Длительность пропуска: случайная (2-3 кадра).
     Каждое видео — уникальная структура таймлайна.

  3. Motion blur (tblend) для сглаживания стыков.

Этот модуль генерирует FFmpeg filter фрагмент для встраивания
в filter_complex матрёшки. Работает с альфа-каналом основного видео:
  - Нормально: alpha = 255 (видео полностью непрозрачно)
  - При пропуске: alpha ≈ 38 (15% видимости видео, 85% подложки)

Поскольку видео лежит НАД подложкой через overlay,
уменьшение alpha обнажает подложку — это и есть нужный эффект.
"""

import logging
import random

from config import FlickerConfig

logger = logging.getLogger(__name__)


def _generate_burst_schedule(
    duration: float, fps: float, cfg: FlickerConfig,
) -> list[tuple[int, int]]:
    """
    Предварительно вычисляет рандомизированное расписание пропусков.

    Возвращает список (start_frame, end_frame) — включительно.
    Во время этих кадров видео станет почти прозрачным.
    """
    schedule = []
    total_frames = int(duration * fps)
    current_frame = 0

    while current_frame < total_frames:
        interval_sec = random.uniform(cfg.burst_interval_min, cfg.burst_interval_max)
        current_frame += int(interval_sec * fps)

        if current_frame >= total_frames:
            break

        burst_len = random.randint(cfg.burst_frames_min, cfg.burst_frames_max)
        end_frame = min(current_frame + burst_len - 1, total_frames - 1)

        schedule.append((current_frame, end_frame))
        current_frame = end_frame + 1

    return schedule


def build_flicker_filters(
    cfg: FlickerConfig,
    fps: float,
    duration: float,
    width: int,
    height: int,
    input_label: str = "[0:v]",
    output_label: str = "[flickered]",
) -> str:
    """
    Строит цепочку FFmpeg-фильтров для мерцания Видео/Подложка.

    Подход:
      1. Добавляем альфа-канал к основному видео (format=yuva420p).
      2. Через geq модулируем alpha:
         - Нормально: alpha = 255 (полностью непрозрачно)
         - Во время пропуска: alpha = (1 - transparency) * 255
      3. Опционально tblend для motion blur (до geq).

    Рандомизация:
      Расписание пропусков вычисляется заранее в Python (random),
      а в FFmpeg передаётся как серия between(N,start,end).
    """
    schedule = _generate_burst_schedule(duration, fps, cfg)

    if not schedule:
        logger.warning("Расписание мерцания пустое (видео слишком короткое?)")
        return f"{input_label}null{output_label}"

    # --- Условие: «мы внутри какого-либо пропуска» ---
    # В geq переменные с большой буквы: N = номер кадра
    conditions = [f"between(N,{s},{e})" for s, e in schedule]
    is_skip_expr = "+".join(conditions)

    # --- Alpha: полная видимость / почти прозрачный ---
    # transparency=0.85 → alpha при пропуске = (1-0.85)*255 ≈ 38
    alpha_normal = 255
    alpha_skip = int((1.0 - cfg.transparency) * 255)

    # geq alpha: в пропуске = alpha_skip, иначе = 255
    geq_alpha = f"if({is_skip_expr},{alpha_skip},{alpha_normal})"

    # Сборка цепочки фильтров
    chain_parts = []

    # Motion blur (до geq, пока формат ещё yuv420p)
    if cfg.motion_blur:
        chain_parts.append("tblend=all_mode=average")

    # Добавляем альфа-канал
    chain_parts.append("format=yuva420p")

    # Модулируем alpha через geq (lum/cb/cr — pass-through)
    chain_parts.append(
        f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='{geq_alpha}'"
    )

    chain = ",".join(chain_parts)
    filter_str = f"{input_label}{chain}{output_label}"

    logger.info(
        "Мерцание: %d пропусков, прозрачность=%d%%, burst=%d–%d кадров, "
        "интервал=%.1f–%.1fс, blur=%s",
        len(schedule),
        int(cfg.transparency * 100),
        cfg.burst_frames_min, cfg.burst_frames_max,
        cfg.burst_interval_min, cfg.burst_interval_max,
        cfg.motion_blur,
    )

    return filter_str
