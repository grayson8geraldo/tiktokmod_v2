"""
Конфигурация утилиты для уникализации видео.
Все параметры обработки задаются здесь.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AnchorConfig:
    """Настройки библиотеки «якорей» (Semantic Anchoring).

    Якорь — короткое видео (природа, город, эстетика), которое:
      1. Показывается 10 кадров на весь экран в начале (Semantic Anchoring).
      2. Используется как видео-подложка (нижний слой) вместо статичной картинки.
    """
    # Корневая папка с якорями
    anchors_root: str = "assets/anchors"

    # Категория (подпапка): 01_High_Trust_Global, 02_Urban_EU и т.д.
    # None = случайный выбор из любой категории
    category: Optional[str] = None

    # Сколько кадров якоря показать на весь экран в начале
    head_frames: int = 10

    # hflip с вероятностью 50%
    random_hflip: bool = True

    # Микро-коррекция экспозиции ±%
    exposure_shift_pct: float = 1.0

    # Микро-шум ISO grain (сила 0-10)
    iso_grain_strength: int = 3

    # Цветовой сдвиг 1-2% для уникальности
    color_shift_pct: float = 1.5

    # Размытие подложки (Gaussian Blur) в пикселях
    background_blur: int = 3

    # Плавное затухание аудио якоря (секунды)
    audio_fade_duration: float = 2.5


@dataclass
class HookGapConfig:
    """Модуль А: Подготовка начала (The Hook Gap).

    Динамический серый фон с микро-шумом + pink noise на 1% громкости.
    Вставляется перед якорем.
    """
    # Длительность 0.3–0.6 сек
    duration: float = 0.4

    # Интенсивность шума на сером фоне (0-20, рекомендуется 3-5)
    noise_strength: int = 4

    # Громкость pink noise (-40 дБ = ~1%)
    pink_noise_db: float = -40.0

    # Crossfade в следующий сегмент (сек)
    crossfade_duration: float = 0.1


@dataclass
class FlickerConfig:
    """Модуль В: Адаптивное мерцание (Soft Interleaving).

    Вместо Видео/Чёрный — Видео/Подложка.
    Когда наступает фаза пропуска, основное видео становится прозрачным на 85%,
    обнажая подложку.
    """
    # Прозрачность основного видео во время «пропуска» (0.85 = 85% прозрачности)
    # Это значит подложка видна на 85%, видео на 15%
    transparency: float = 0.85

    # Интервал между вставками подложки (сек, рандомизируется)
    burst_interval_min: float = 1.5
    burst_interval_max: float = 2.5

    # Длительность вставки подложки (кадры, рандомизируется)
    burst_frames_min: int = 2
    burst_frames_max: int = 3

    # Motion blur: tblend для сглаживания стыков (True/False)
    motion_blur: bool = True


@dataclass
class MatryoshkaConfig:
    """Модуль Б: Многослойная композиция (Layering).

    Слой 1: Видео-подложка (якорь, размытый).
    Слой 2: Основное видео, уменьшенное до 94-97%.
    Эффект края: тонкая тень/glow для стирания границы.
    """
    output_width: int = 1080
    output_height: int = 1920
    # Масштаб основного видео (0.94–0.97)
    video_scale: float = 0.96
    # Микро-сдвиг позиции (пиксели)
    position_jitter: int = 3
    # Сила шума ISO grain (0-10)
    noise_opacity: float = 0.02
    # Тень под верхним видео (drop shadow) — сила размытия тени
    shadow_strength: int = 4
    # Прозрачность тени (0.0–1.0)
    shadow_opacity: float = 0.3


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
    """Главная конфигурация пайплайна.

    Новый поток:
      1. Подготовка якоря (выбор, уникализация)
      2. Hook Gap (серый шум 0.3-0.6с) + crossfade в якорь
      3. Якорь на весь экран (10 кадров = 0.3с)
      4. Матрёшка (подложка-якорь + видео 95-97% + мерцание + шум)
      5. Аудио-обработка
      6. Цифровое ДНК
    """
    anchor: AnchorConfig = field(default_factory=AnchorConfig)
    hook_gap: HookGapConfig = field(default_factory=HookGapConfig)
    flicker: FlickerConfig = field(default_factory=FlickerConfig)
    matryoshka: MatryoshkaConfig = field(default_factory=MatryoshkaConfig)
    digital_dna: DigitalDNAConfig = field(default_factory=DigitalDNAConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)

    temp_dir: str = "/tmp/videomod_temp"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
