"""
Веб-интерфейс утилиты для уникализации видео.
Flask-приложение с загрузкой, настройкой параметров и скачиванием результата.
"""

import logging
import os
import secrets
import threading
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
    AnchorConfig,
    AudioConfig,
    DigitalDNAConfig,
    FlickerConfig,
    HookGapConfig,
    MatryoshkaConfig,
    PipelineConfig,
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

    # --- Anchor (якорь) ---
    cfg.anchor.anchors_root = form.get(
        "anchor_root",
        os.path.join(BASE_DIR, "assets", "anchors"),
    )
    category = form.get("anchor_category", "")
    cfg.anchor.category = category if category else None
    cfg.anchor.head_frames = int(form.get("anchor_head_frames", 10))
    cfg.anchor.random_hflip = form.get("anchor_hflip") == "on"
    cfg.anchor.exposure_shift_pct = float(form.get("anchor_exposure", 1.0))
    cfg.anchor.color_shift_pct = float(form.get("anchor_color_shift", 1.5))
    cfg.anchor.iso_grain_strength = int(form.get("anchor_grain", 3))
    cfg.anchor.background_blur = int(form.get("anchor_blur", 3))
    cfg.anchor.audio_fade_duration = float(form.get("anchor_audio_fade", 2.5))

    # --- Hook Gap ---
    cfg.hook_gap.duration = float(form.get("hg_duration", 0.4))
    cfg.hook_gap.noise_strength = int(form.get("hg_noise", 4))
    cfg.hook_gap.pink_noise_db = float(form.get("hg_pink_db", -40.0))
    cfg.hook_gap.crossfade_duration = float(form.get("hg_crossfade", 0.1))

    # --- Matryoshka ---
    cfg.matryoshka.output_width = int(form.get("mt_width", 1080))
    cfg.matryoshka.output_height = int(form.get("mt_height", 1920))
    cfg.matryoshka.video_scale = float(form.get("mt_scale", 0.96))
    cfg.matryoshka.position_jitter = int(form.get("mt_jitter", 3))
    cfg.matryoshka.noise_opacity = float(form.get("mt_noise", 0.02))
    cfg.matryoshka.shadow_strength = int(form.get("mt_shadow_strength", 4))
    cfg.matryoshka.shadow_opacity = float(form.get("mt_shadow_opacity", 0.3))

    # --- Flicker (Soft Interleaving) ---
    cfg.flicker.transparency = float(form.get("fl_transparency", 0.85))
    cfg.flicker.burst_interval_min = float(form.get("fl_burst_int_min", 1.5))
    cfg.flicker.burst_interval_max = float(form.get("fl_burst_int_max", 2.5))
    cfg.flicker.burst_frames_min = int(form.get("fl_burst_fr_min", 2))
    cfg.flicker.burst_frames_max = int(form.get("fl_burst_fr_max", 3))
    cfg.flicker.motion_blur = form.get("fl_blur") == "on"

    # --- Digital DNA ---
    cfg.digital_dna.enabled = form.get("dd_enabled") == "on"
    cfg.digital_dna.strip_metadata = form.get("dd_strip_meta") == "on"
    cfg.digital_dna.inject_fake_metadata = form.get("dd_fake_meta") == "on"
    cfg.digital_dna.trim_tail_frames_min = int(form.get("dd_trim_min", 2))
    cfg.digital_dna.trim_tail_frames_max = int(form.get("dd_trim_max", 5))
    cfg.digital_dna.audio_bitrate_shift_kbps = int(form.get("dd_bitrate_shift", 1))
    cfg.digital_dna.horizontal_flip = form.get("dd_flip") == "on"

    # --- Dirty Encode ---
    cfg.digital_dna.fps_jitter = form.get("dd_fps_jitter") == "on"
    cfg.digital_dna.fps_jitter_range = float(form.get("dd_fps_range", 0.05))
    cfg.digital_dna.audio_drift_max_ms = float(form.get("dd_audio_drift", 1.0))

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
        class ProgressHandler(logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                jobs[job_id]["message"] = msg
                if "Шаг 1/6" in msg:
                    jobs[job_id]["progress"] = 5
                elif "Шаг 2/6" in msg:
                    jobs[job_id]["progress"] = 15
                elif "Шаг 3/6" in msg:
                    jobs[job_id]["progress"] = 25
                elif "Шаг 4/6" in msg:
                    jobs[job_id]["progress"] = 50
                elif "Шаг 5/6" in msg:
                    jobs[job_id]["progress"] = 70
                elif "Шаг 6/6" in msg:
                    jobs[job_id]["progress"] = 85
                elif "Обработка завершена" in msg:
                    jobs[job_id]["progress"] = 100

        handler = ProgressHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        for logger_name in (
            "pipeline", "modules.anchor_manager", "modules.hook_gap",
            "modules.matryoshka", "modules.flicker",
            "modules.digital_dna", "modules.audio",
        ):
            logging.getLogger(logger_name).addHandler(handler)

        run_pipeline(input_path, output_path, cfg)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["message"] = "Обработка завершена"
        jobs[job_id]["output_path"] = output_path

        for logger_name in (
            "pipeline", "modules.anchor_manager", "modules.hook_gap",
            "modules.matryoshka", "modules.flicker",
            "modules.digital_dna", "modules.audio",
        ):
            logging.getLogger(logger_name).removeHandler(handler)

    except Exception as e:
        logger.error("Ошибка обработки задачи %s: %s", job_id, e, exc_info=True)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)

    finally:
        jobs[job_id]["finished_at"] = datetime.now().isoformat()
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

    job_id = str(uuid.uuid4())[:8]
    ext = file.filename.rsplit(".", 1)[1].lower()
    input_filename = f"{job_id}_input.{ext}"
    input_path = os.path.join(UPLOAD_DIR, input_filename)
    file.save(input_path)

    output_filename = f"{job_id}_output.mp4"
    output_path = os.path.join(PROCESSED_DIR, output_filename)

    cfg = _build_config_from_form(request.form)

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "В очереди...",
        "input_filename": file.filename,
        "output_filename": output_filename,
        "created_at": datetime.now().isoformat(),
    }

    thread = threading.Thread(
        target=_process_job,
        args=(job_id, input_path, output_path, cfg),
        daemon=True,
    )
    thread.start()

    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/job/<job_id>")
def job_status_page(job_id: str):
    if job_id not in jobs:
        flash("Задача не найдена", "error")
        return redirect(url_for("index"))
    return render_template("status.html", job_id=job_id, job=jobs[job_id])


@app.route("/api/job/<job_id>")
def job_status_api(job_id: str):
    if job_id not in jobs:
        return jsonify({"error": "Задача не найдена"}), 404
    return jsonify(jobs[job_id])


@app.route("/download/<job_id>")
def download(job_id: str):
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
    from dataclasses import asdict
    return jsonify(asdict(PipelineConfig()))


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
