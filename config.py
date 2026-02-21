"""
Конфигурация утилиты для уникализации видео.
Все параметры обработки задаются здесь.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZeroFrameConfig:
    """Настройки нулевого кадра (серый сегмент)."""
    # Длительность серого сегмента (сек)
    gray_duration: float = 0.3
    # "fade" / "cut"
    transition: str = "fade"
    fade_duration: float = 0.2


@dataclass
class ImageIntroConfig:
    """Настройки вступительной картинки."""
    # Путь к изображению (подгружается из формы)
    image_path: Optional[str] = None
    # Длительность показа картинки как отдельного сегмента (сек)
    duration: float = 0.7
    # "fade" / "cut"
    transition: str = "fade"
    fade_duration: float = 0.2


@dataclass
class FlickerConfig:
    """Кадровое мерцание (overlay с переменной прозрачностью + рандомизация).

    Вместо жёсткого select/drawbox — overlay чёрного слоя с sin/cos
    модуляцией прозрачности. Интервалы и длительности рандомизированы,
    чтобы каждое видео имело уникальную структуру таймлайна.
    """
    # Диапазон прозрачности чёрного оверлея на «тёмных» кадрах.
    # alpha_min=0.7, alpha_max=0.9 → видимость видео 10-30%
    alpha_min: float = 0.7
    alpha_max: float = 0.9

    # Интервал между пачками тёмных кадров (сек, рандомизируется)
    burst_interval_min: float = 1.8
    burst_interval_max: float = 2.4

    # Длительность пачки тёмных кадров (рандомизируется)
    burst_frames_min: int = 2
    burst_frames_max: int = 4

    # Motion blur: tblend для сглаживания стыков (True/False)
    motion_blur: bool = True


@dataclass
class MatryoshkaConfig:
    """Визуальная «Матрёшка» (подложка + видео + шум)."""
    output_width: int = 1080
    output_height: int = 1920
    # Масштаб основного видео (0.90–0.99)
    video_scale: float = 0.96
    # Микро-сдвиг позиции (пиксели)
    position_jitter: int = 3
    # Сила шума (0.005–0.05)
    noise_opacity: float = 0.02


@dataclass
class DigitalDNAConfig:
    """Уникализация «Цифрового ДНК»."""
    enabled: bool = True
    strip_metadata: bool = True
    inject_fake_metadata: bool = True
    trim_tail_frames_min: int = 2
    trim_tail_frames_max: int = 5
    audio_bitrate_shift_kbps: int = 1
    horizontal_flip: bool = False

    # --- Dirty Encode: полезный шум для антидетекции ---
    # FPS Jitter: случайное отклонение fps (29.976, 30.012 и т.д.)
    fps_jitter: bool = True
    fps_jitter_range: float = 0.05  # ±0.05 от оригинала

    # Audio Drift: микро-сдвиг аудио относительно видео (мс)
    audio_drift_max_ms: float = 1.0


@dataclass
class AudioConfig:
    """Аудио-модуль."""
    enabled: bool = True
    pitch_shift_semitones: float = 0.2
    pitch_direction: str = "random"
    pink_noise_volume_db: float = -45.0


@dataclass
class PipelineConfig:
    """Главная конфигурация пайплайна."""
    # Режим работы:
    #   "gray_image_flicker" — серый(0.3с) + картинка(0.7с) → картинка-подложка + видео с мерцанием
    #   "gray_flicker"       — серый(1с) → видео с мерцанием (без подложки)
    #   "image_video"        — картинка(0.3-1с) → картинка-подложка + видео (без мерцания)
    preset: str = "gray_image_flicker"

    zero_frame: ZeroFrameConfig = field(default_factory=ZeroFrameConfig)
    image_intro: ImageIntroConfig = field(default_factory=ImageIntroConfig)
    flicker: FlickerConfig = field(default_factory=FlickerConfig)
    matryoshka: MatryoshkaConfig = field(default_factory=MatryoshkaConfig)
    digital_dna: DigitalDNAConfig = field(default_factory=DigitalDNAConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)

    temp_dir: str = "/tmp/videomod_temp"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
