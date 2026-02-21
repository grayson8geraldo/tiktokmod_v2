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
    """Кадровое мерцание (alpha-blending + motion blur)."""
    # Паттерн: кол-во видимых кадров и кол-во затемнённых кадров
    visible_frames: int = 2
    dark_frames: int = 1
    # Alpha-blending: видимость видео на «тёмных» кадрах (0.0 = полностью чёрный, 1.0 = полностью видно)
    dark_opacity: float = 0.18
    # Motion blur: tblend для сглаживания стыков (True/False)
    motion_blur: bool = True
    # Сдвиг фазы: каждые N сек — пачка тёмных кадров
    phase_shift_interval: float = 2.0
    phase_shift_dark_frames: int = 3


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
