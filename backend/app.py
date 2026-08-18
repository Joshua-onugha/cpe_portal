import os
import io
import math
import statistics
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
)

import requests as http_requests
from PyPDF2 import PdfReader
from docx import Document as DocxDocument

# ─── App Setup ───────────────────────────────────────────────────────────────

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "uniben_cpe_secret")
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "uniben_cpe_jwt_secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///project.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Allow the Vercel frontend origin (set via env in production)
frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
CORS(app, origins=[frontend_url, "http://localhost:3000"], supports_credentials=True)

jwt = JWTManager(app)
db = SQLAlchemy(app)

WASITAI_API_KEY = os.environ.get("WASITAI_API_KEY", "")
WASITAI_BASE_URL = "https://www.wasitaigenerated.com/api/v1"

# ─── Database Model ──────────────────────────────────────────────────────────


class AnalysisRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    matric_no = db.Column(db.String(20), unique=True, nullable=False)
    filename = db.Column(db.String(100), nullable=False)
    ai_score = db.Column(db.Integer, nullable=False)
    verdict = db.Column(db.String(20), nullable=False)
    perplexity = db.Column(db.Float, nullable=False)
    burstiness = db.Column(db.Float, nullable=False)
    consistency = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()

# ─── File Text Extraction ────────────────────────────────────────────────────


def extract_text_from_pdf(file_storage) -> str:
    """Extract text from a PDF file object."""
    reader = PdfReader(io.BytesIO(file_storage.read()))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    file_storage.seek(0)  # rewind so it can be read again if needed
    return text.strip()


def extract_text_from_docx(file_storage) -> str:
    """Extract text from a DOCX file object."""
    doc = DocxDocument(io.BytesIO(file_storage.read()))
    text = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    file_storage.seek(0)
    return text.strip()


def extract_text(filename: str, file_storage) -> str:
    """Route to the right extractor based on file extension."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(file_storage)
    elif lower.endswith(".docx"):
        return extract_text_from_docx(file_storage)
    else:
        raise ValueError(f"Unsupported file type: {filename}")


# ─── WasItAI API ─────────────────────────────────────────────────────────────

CHUNK_SIZE = 4000  # words per chunk — keeps us well under the 413 limit


def chunk_text(text: str, max_words: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks of roughly max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


def call_wasitai(content: str) -> dict:
    """Call the WasItAI /detect/text endpoint. Returns the JSON response."""
    resp = http_requests.post(
        f"{WASITAI_BASE_URL}/detect/text",
        headers={"Authorization": f"Bearer {WASITAI_API_KEY}"},
        json={"content": content},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def aggregate_chunk_results(results: list[dict]) -> dict:
    """Merge multiple chunk results into a single document-level result."""
    all_sentences = []
    confidences = []

    for r in results:
        all_sentences.extend(r.get("sentences", []))
        confidences.append(r.get("confidence", 0))

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    is_ai = avg_confidence > 0.5

    return {
        "isAI": is_ai,
        "confidence": round(avg_confidence, 4),
        "model": results[0].get("model", "unknown") if results else "unknown",
        "sentences": all_sentences,
    }


def analyse_text(text: str) -> dict:
    """
    Full pipeline: chunk long text, call WasItAI per chunk,
    aggregate, then derive the metrics our UI expects.
    """
    chunks = chunk_text(text)

    if len(chunks) == 1:
        raw = call_wasitai(chunks[0])
    else:
        chunk_results = []
        for chunk in chunks:
            chunk_results.append(call_wasitai(chunk))
        raw = aggregate_chunk_results(chunk_results)

    confidence = raw["confidence"]  # 0.0 – 1.0
    sentences = raw.get("sentences", [])

    # ── Map to existing model fields ──────────────────────────────────────
    ai_score = round(confidence * 100)

    if confidence > 0.6:
        verdict = "AI Generated"
    elif confidence > 0.3:
        verdict = "Mixed"
    else:
        verdict = "Human Written"

    # Derive secondary metrics from sentence-level data
    if sentences:
        sentence_scores = [s.get("confidence", 0) for s in sentences]
        human_scores = [s.get("scores", {}).get("human", 0) for s in sentences]

        # Perplexity proxy: variance in sentence AI scores (higher = more erratic)
        perplexity = round(
            statistics.stdev(sentence_scores) * 100 if len(sentence_scores) > 1 else 0,
            1,
        )

        # Burstiness proxy: how uneven the AI-flag distribution is
        ai_flags = [1 if s.get("isAI", False) else 0 for s in sentences]
        if len(ai_flags) > 1:
            burstiness = round(statistics.stdev(ai_flags) * 100, 1)
        else:
            burstiness = 0.0

        # Consistency: % of sentences agreeing with the document-level verdict
        agreement = sum(1 for s in sentences if s.get("isAI", False) == raw["isAI"])
        consistency = round((agreement / len(sentences)) * 100) if sentences else 0
    else:
        perplexity = 0.0
        burstiness = 0.0
        consistency = 0

    return {
        "ai_score": ai_score,
        "verdict": verdict,
        "perplexity": perplexity,
        "burstiness": burstiness,
        "consistency": consistency,
        "is_ai": raw["isAI"],
        "confidence": confidence,
        "model": raw.get("model", ""),
        "sentence_count": len(sentences),
    }


# ─── Auth Routes ─────────────────────────────────────────────────────────────


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = data.get("username", "")
    password = data.get("password", "")

    # TODO: replace with real user table + hashed passwords
    if username == "admin" and password == "uniben2026":
        token = create_access_token(identity=username)
        return jsonify({"success": True, "token": token})

    return jsonify({"error": "Invalid credentials"}), 401


# ─── Student Routes ──────────────────────────────────────────────────────────


@app.route("/api/analyze", methods=["POST"])
def analyze():
    student_name = (request.form.get("studentName") or "").strip().upper()
    matric_no = (request.form.get("matricNo") or "").strip().upper()

    if not matric_no or not student_name:
        return jsonify({"error": "Student Name and Matriculation Number are required!"}), 400

    # Duplicate gatekeeper
    if AnalysisRecord.query.filter_by(matric_no=matric_no).first():
        return (
            jsonify(
                {
                    "error": f"Submission Blocked: Matriculation Number {matric_no} has already been scanned."
                }
            ),
            400,
        )

    # File check
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded!"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file!"}), 400

    # Extract text
    try:
        text = extract_text(file.filename, file)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {e}"}), 400

    if not text:
        return jsonify({"error": "Could not extract text from the uploaded file."}), 400

    # Call WasItAI
    if not WASITAI_API_KEY:
        return jsonify({"error": "WASITAI_API_KEY is not configured on the server."}), 500

    try:
        result = analyse_text(text)
    except http_requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        body = {}
        try:
            body = e.response.json()
        except Exception:
            pass
        if status == 402:
            return (
                jsonify({"error": "Out of detection credits. Please contact admin."}),
                402,
            )
        return (
            jsonify({"error": f"Detection API error: {body.get('error', str(e))}"}),
            status,
        )
    except http_requests.exceptions.Timeout:
        return jsonify({"error": "Detection API timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Analysis failed: {e}"}), 500

    # Save to database
    new_record = AnalysisRecord(
        student_name=student_name,
        matric_no=matric_no,
        filename=file.filename,
        ai_score=result["ai_score"],
        verdict=result["verdict"],
        perplexity=result["perplexity"],
        burstiness=result["burstiness"],
        consistency=result["consistency"],
    )
    db.session.add(new_record)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "score": result["ai_score"],
            "verdict": result["verdict"],
            "perp": result["perplexity"],
            "burst": result["burstiness"],
            "cons": result["consistency"],
            "report_id": new_record.id,
        }
    )


# ─── Admin Routes (JWT-protected) ───────────────────────────────────────────


@app.route("/api/dashboard_data")
@jwt_required()
def dashboard_data():
    records = AnalysisRecord.query.order_by(AnalysisRecord.timestamp.desc()).all()
    return jsonify(
        [
            {
                "id": r.id,
                "student_name": r.student_name,
                "matric_no": r.matric_no,
                "ai_score": r.ai_score,
                "verdict": r.verdict,
                "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M"),
            }
            for r in records
        ]
    )


@app.route("/api/report/<int:id>")
def report(id):
    r = AnalysisRecord.query.get_or_404(id)
    return jsonify(
        {
            "id": r.id,
            "student_name": r.student_name,
            "matric_no": r.matric_no,
            "filename": r.filename,
            "ai_score": r.ai_score,
            "verdict": r.verdict,
            "perplexity": r.perplexity,
            "burstiness": r.burstiness,
            "consistency": r.consistency,
            "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M"),
        }
    )


@app.route("/api/delete/<int:id>", methods=["POST"])
@jwt_required()
def delete_record(id):
    record = AnalysisRecord.query.get_or_404(id)
    try:
        db.session.delete(record)
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete record."}), 500


# ─── Health check ────────────────────────────────────────────────────────────


@app.route("/health")
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
