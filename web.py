"""
Веб-интерфейс утилиты для уникализации видео.
Flask-приложение с загрузкой, настройкой параметров и скачиванием результата.
"""

import json
import logging
import os
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from config import (
    AudioConfig,
    DigitalDNAConfig,
    FlickerConfig,
    MatryoshkaConfig,
    PipelineConfig,
    ZeroFrameConfig,
)
from pipeline import run_pipeline

# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

for d in (UPLOAD_DIR, PROCESSED_DIR, TEMP_DIR):
    os.makedirs(d, exist_ok=True)

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "m4v"}
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Хранилище задач обработки: {job_id: {status, progress, message, ...}}
jobs: dict[str, dict] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("web")


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _build_config_from_form(form: dict) -> PipelineConfig:
    """Преобразует данные формы в PipelineConfig."""
    cfg = PipelineConfig(temp_dir=TEMP_DIR)

    # --- Zero Frame ---
    cfg.zero_frame.enabled = form.get("zf_enabled") == "on"
    cfg.zero_frame.mode = form.get("zf_mode", "gray")
    cfg.zero_frame.duration = float(form.get("zf_duration", 0.5))
    cfg.zero_frame.transition = form.get("zf_transition", "fade")
    cfg.zero_frame.fade_duration = float(form.get("zf_fade_duration", 0.3))

    # --- Matryoshka ---
    cfg.matryoshka.enabled = form.get("mt_enabled") == "on"
    cfg.matryoshka.output_width = int(form.get("mt_width", 1080))
    cfg.matryoshka.output_height = int(form.get("mt_height", 1920))
    cfg.matryoshka.video_scale = float(form.get("mt_scale", 0.96))
    cfg.matryoshka.position_jitter = int(form.get("mt_jitter", 3))
    cfg.matryoshka.noise_opacity = float(form.get("mt_noise", 0.02))

    # --- Flicker ---
    cfg.flicker.enabled = form.get("fl_enabled") == "on"
    cfg.flicker.interleave_every = int(form.get("fl_interleave", 2))
    cfg.flicker.phase_shift_interval = float(form.get("fl_phase_interval", 2.0))
    cfg.flicker.phase_shift_black_frames = int(form.get("fl_black_frames", 3))

    # --- Digital DNA ---
    cfg.digital_dna.enabled = form.get("dd_enabled") == "on"
    cfg.digital_dna.strip_metadata = form.get("dd_strip_meta") == "on"
    cfg.digital_dna.inject_fake_metadata = form.get("dd_fake_meta") == "on"
    cfg.digital_dna.trim_tail_frames_min = int(form.get("dd_trim_min", 2))
    cfg.digital_dna.trim_tail_frames_max = int(form.get("dd_trim_max", 5))
    cfg.digital_dna.audio_bitrate_shift_kbps = int(form.get("dd_bitrate_shift", 1))
    cfg.digital_dna.horizontal_flip = form.get("dd_flip") == "on"

    # --- Audio ---
    cfg.audio.enabled = form.get("au_enabled") == "on"
    cfg.audio.pitch_shift_semitones = float(form.get("au_pitch", 0.2))
    cfg.audio.pitch_direction = form.get("au_pitch_dir", "random")
    cfg.audio.pink_noise_volume_db = float(form.get("au_pink_db", -45.0))

    return cfg


# ---------------------------------------------------------------------------
# Фоновая обработка
# ---------------------------------------------------------------------------


def _process_job(job_id: str, input_path: str, output_path: str, cfg: PipelineConfig):
    """Запускает пайплайн в фоновом потоке и обновляет статус задачи."""
    jobs[job_id]["status"] = "processing"
    jobs[job_id]["started_at"] = datetime.now().isoformat()

    try:
        # Подменяем logger пайплайна, чтобы перехватывать прогресс
        pipeline_logger = logging.getLogger("pipeline_progress")

        class ProgressHandler(logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                jobs[job_id]["message"] = msg
                # Грубая оценка прогресса по шагам
                if "Шаг 1/5" in msg:
                    jobs[job_id]["progress"] = 10
                elif "Шаг 2/5" in msg:
                    jobs[job_id]["progress"] = 25
                elif "Шаг 3/5" in msg:
                    jobs[job_id]["progress"] = 45
                elif "Шаг 4/5" in msg:
                    jobs[job_id]["progress"] = 65
                elif "Шаг 5/5" in msg:
                    jobs[job_id]["progress"] = 80
                elif "Обработка завершена" in msg:
                    jobs[job_id]["progress"] = 100

        handler = ProgressHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        # Добавляем handler ко всем модулям пайплайна
        for logger_name in (
            "pipeline", "modules.zero_frame", "modules.matryoshka",
            "modules.flicker", "modules.digital_dna", "modules.audio",
        ):
            logging.getLogger(logger_name).addHandler(handler)

        run_pipeline(input_path, output_path, cfg)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["message"] = "Обработка завершена"
        jobs[job_id]["output_path"] = output_path

        # Удаляем handlers
        for logger_name in (
            "pipeline", "modules.zero_frame", "modules.matryoshka",
            "modules.flicker", "modules.digital_dna", "modules.audio",
        ):
            logging.getLogger(logger_name).removeHandler(handler)

    except Exception as e:
        logger.error("Ошибка обработки задачи %s: %s", job_id, e, exc_info=True)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)

    finally:
        jobs[job_id]["finished_at"] = datetime.now().isoformat()
        # Удаляем исходный загруженный файл
        if os.path.isfile(input_path):
            os.remove(input_path)


# ---------------------------------------------------------------------------
# Маршруты
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    """Загрузка видео и запуск обработки."""
    if "video" not in request.files:
        flash("Файл не выбран", "error")
        return redirect(url_for("index"))

    file = request.files["video"]
    if file.filename == "":
        flash("Файл не выбран", "error")
        return redirect(url_for("index"))

    if not _allowed_file(file.filename):
        flash(
            f"Недопустимый формат. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}",
            "error",
        )
        return redirect(url_for("index"))

    # Сохраняем файл
    job_id = str(uuid.uuid4())[:8]
    ext = file.filename.rsplit(".", 1)[1].lower()
    input_filename = f"{job_id}_input.{ext}"
    input_path = os.path.join(UPLOAD_DIR, input_filename)
    file.save(input_path)

    output_filename = f"{job_id}_output.mp4"
    output_path = os.path.join(PROCESSED_DIR, output_filename)

    # Собираем конфиг из формы
    cfg = _build_config_from_form(request.form)

    # Обработка фонового изображения для матрёшки
    if "mt_background" in request.files:
        bg_file = request.files["mt_background"]
        if bg_file.filename:
            bg_path = os.path.join(UPLOAD_DIR, f"{job_id}_bg.{bg_file.filename.rsplit('.', 1)[-1]}")
            bg_file.save(bg_path)
            cfg.matryoshka.background_image = bg_path

    # Обработка изображения нулевого кадра
    if "zf_image" in request.files:
        zf_file = request.files["zf_image"]
        if zf_file.filename:
            zf_path = os.path.join(UPLOAD_DIR, f"{job_id}_zf.{zf_file.filename.rsplit('.', 1)[-1]}")
            zf_file.save(zf_path)
            cfg.zero_frame.image_path = zf_path
            cfg.zero_frame.mode = "image"

    # Создаём задачу
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "В очереди...",
        "input_filename": file.filename,
        "output_filename": output_filename,
        "created_at": datetime.now().isoformat(),
    }

    # Запускаем в фоне
    thread = threading.Thread(
        target=_process_job,
        args=(job_id, input_path, output_path, cfg),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/job/<job_id>")
def job_status_page(job_id: str):
    """Страница статуса задачи."""
    if job_id not in jobs:
        flash("Задача не найдена", "error")
        return redirect(url_for("index"))
    return render_template("status.html", job_id=job_id, job=jobs[job_id])


@app.route("/api/job/<job_id>")
def job_status_api(job_id: str):
    """API для получения статуса задачи (polling)."""
    if job_id not in jobs:
        return jsonify({"error": "Задача не найдена"}), 404
    return jsonify(jobs[job_id])


@app.route("/download/<job_id>")
def download(job_id: str):
    """Скачивание обработанного файла."""
    if job_id not in jobs:
        flash("Задача не найдена", "error")
        return redirect(url_for("index"))

    job = jobs[job_id]
    if job["status"] != "done":
        flash("Файл ещё не готов", "error")
        return redirect(url_for("job_status_page", job_id=job_id))

    output_path = job.get("output_path")
    if not output_path or not os.path.isfile(output_path):
        flash("Файл не найден на сервере", "error")
        return redirect(url_for("index"))

    original_name = job.get("input_filename", "video.mp4")
    base = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    download_name = f"{base}_processed.mp4"

    return send_file(
        output_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="video/mp4",
    )


@app.route("/api/config/default")
def default_config():
    """Возвращает конфигурацию по умолчанию."""
    from dataclasses import asdict
    return jsonify(asdict(PipelineConfig()))


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
