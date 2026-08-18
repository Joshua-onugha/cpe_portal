import os
import io
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

from PyPDF2 import PdfReader
from docx import Document as DocxDocument
from app.stylometry.engine import analyze_text

# ─── App Setup ───────────────────────────────────────────────────────────────

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "uniben_cpe_secret")
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "uniben_cpe_jwt_secret")
db_url = os.environ.get("DATABASE_URL", "sqlite:///project.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Allow the Vercel frontend origin
allowed_origins = [
    "https://cpe-portal.vercel.app",
    "http://localhost:3000",
    "http://localhost:5500",
]
frontend_url = os.environ.get("FRONTEND_URL")
if frontend_url:
    allowed_origins.append(frontend_url)
CORS(app, origins=allowed_origins, supports_credentials=True)

jwt = JWTManager(app)
db = SQLAlchemy(app)

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


# ─── Stylometry Analysis ──────────────────────────────────────────────────────


def analyse_text(text: str) -> dict:
    """
    Run local stylometry analysis and map to the fields our UI expects.
    """
    result = analyze_text(text)

    if result.get("status") == "insufficient_text":
        return {"error": result.get("message", "Not enough text for analysis.")}

    ai_score = result.get("ai_probability", 0)
    classification = result.get("classification", "mixed_or_uncertain")

    # Map classification to verdict strings
    verdict_map = {
        "likely_ai": "AI Generated",
        "mixed_or_uncertain": "Mixed",
        "likely_human": "Human Written",
    }
    verdict = verdict_map.get(classification, "Mixed")

    # Use statistics from the engine
    stats = result.get("statistics", {})
    signals = result.get("signals", [])

    # Perplexity proxy: use readability score (inverted - lower readability = more perplexing)
    readability = stats.get("readability_proxy", 50)
    perplexity = round(max(0, min(100, 100 - readability)), 1)

    # Burstiness: extract from signals or compute from statistics
    burstiness_signal = next((s for s in signals if s["name"] == "sentence_uniformity"), None)
    burstiness = round((1 - burstiness_signal["value"]) * 100, 1) if burstiness_signal else 50.0

    # Consistency: use confidence from the engine
    consistency = round(result.get("confidence", 50))

    return {
        "ai_score": round(ai_score),
        "verdict": verdict,
        "perplexity": perplexity,
        "burstiness": burstiness,
        "consistency": consistency,
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

    # Run stylometry analysis
    result = analyse_text(text)
    if "error" in result:
        return jsonify({"error": result["error"]}), 400

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
