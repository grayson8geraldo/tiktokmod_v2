"""
Конфигурация утилиты для уникализации видео.
Все параметры обработки задаются здесь.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZeroFrameConfig:
    """Модуль 1: Подготовка «нулевого» кадра."""
    enabled: bool = True
    # "gray" — серый кадр #808080, "image" — произвольное изображение
    mode: str = "gray"
    # Путь к изображению (используется при mode="image")
    image_path: Optional[str] = None
    # Длительность сегмента в секундах (0.1–1.5)
    duration: float = 0.5
    # "fade" — плавный переход, "cut" — резкий
    transition: str = "fade"
    # Длительность фейда в секундах (при transition="fade")
    fade_duration: float = 0.3


@dataclass
class MatryoshkaConfig:
    """Модуль 2: Визуальная «Матрёшка» (слои)."""
    enabled: bool = True
    # Размеры выходного кадра
    output_width: int = 1080
    output_height: int = 1920
    # Путь к фоновому изображению (подложка)
    background_image: Optional[str] = None
    # Масштаб основного видео (0.95–0.98 от оригинала)
    video_scale: float = 0.96
    # Случайный микро-сдвиг позиции (в пикселях, 0 — без сдвига)
    position_jitter: int = 3
    # Прозрачность шума-оверлея (1–3%)
    noise_opacity: float = 0.02


@dataclass
class FlickerConfig:
    """Модуль 3: Кадровое мерцание (Interleaving)."""
    enabled: bool = True
    # Каждый N-й кадр заменяется чёрным (чередование 1:1)
    interleave_every: int = 2
    # Интервал «паузы» в секундах — каждые N сек вставляется пачка чёрных кадров
    phase_shift_interval: float = 2.0
    # Количество последовательных чёрных кадров при «паузе»
    phase_shift_black_frames: int = 3


@dataclass
class DigitalDNAConfig:
    """Модуль 4: Уникализация «Цифрового ДНК»."""
    enabled: bool = True
    # Удаление EXIF и инъекция фейковых метаданных
    strip_metadata: bool = True
    inject_fake_metadata: bool = True
    # Микро-обрезка: удалить случайные 2–5 кадров в конце
    trim_tail_frames_min: int = 2
    trim_tail_frames_max: int = 5
    # Изменение битрейта аудио (±1–2 кбит/с)
    audio_bitrate_shift_kbps: int = 1
    # Горизонтальный флип
    horizontal_flip: bool = False


@dataclass
class AudioConfig:
    """Модуль 5: Аудио-модуль."""
    enabled: bool = True
    # Pitch shift: ±0.1–0.3 полутона
    pitch_shift_semitones: float = 0.2
    # Направление: "up", "down", "random"
    pitch_direction: str = "random"
    # Громкость розового шума (в дБ ниже основного трека, напр. -40 дБ)
    pink_noise_volume_db: float = -45.0


@dataclass
class PipelineConfig:
    """Главная конфигурация пайплайна."""
    zero_frame: ZeroFrameConfig = field(default_factory=ZeroFrameConfig)
    matryoshka: MatryoshkaConfig = field(default_factory=MatryoshkaConfig)
    flicker: FlickerConfig = field(default_factory=FlickerConfig)
    digital_dna: DigitalDNAConfig = field(default_factory=DigitalDNAConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    # Директория для промежуточных файлов
    temp_dir: str = "/tmp/videomod_temp"
    # FFmpeg/FFprobe пути (None = из PATH)
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
