import os
from datetime import datetime
import random # (Using random for mock AI stats until you plug in your RoBERTa model)
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = "uniben_cpe_deployment_secret"

# --- DATABASE SETUP ---
BASE_DIR = os.path.abspath(os.path.dirname(__name__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'project.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- DATABASE MODEL ---
class AnalysisRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    matric_no = db.Column(db.String(20), unique=True, nullable=False) # Enforces 1 submission per student
    filename = db.Column(db.String(100), nullable=False)
    ai_score = db.Column(db.Integer, nullable=False)
    verdict = db.Column(db.String(20), nullable=False)
    perplexity = db.Column(db.Float, nullable=False)
    burstiness = db.Column(db.Float, nullable=False)
    consistency = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# --- HTML PAGE ROUTES ---
@app.route('/')
def portal():
    return render_template('ai-detector-portal.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == 'admin' and request.form.get('password') == 'uniben2026':
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('ai-detector-dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('portal'))

@app.route('/report/<int:id>')
def report(id):
    record = AnalysisRecord.query.get_or_404(id)
    return render_template('report.html', r=record)


# --- API ROUTES ---

@app.route('/analyze', methods=['POST'])
def analyze():
    student_name = request.form.get('studentName', '').upper()
    matric_no = request.form.get('matricNo', '').upper()

    # 1. ANTI-DUPLICATE GATEKEEPER
    if not matric_no or not student_name:
        return jsonify({"error": "Student Name and Matriculation Number are required!"}), 400

    existing_student = AnalysisRecord.query.filter_by(matric_no=matric_no).first()
    if existing_student:
        return jsonify({
            "error": f"Submission Blocked: Matriculation Number {matric_no} has already been scanned. Multiple submissions are not allowed."
        }), 400

    # 2. FILE CHECK
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded!"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file!"}), 400

    # 3. MOCK AI ANALYSIS
    ai_score = random.randint(10, 95)
    verdict = "AI Generated" if ai_score > 60 else ("Mixed" if ai_score > 30 else "Human Written")
    perplexity = round(random.uniform(10.5, 80.5), 1)
    burstiness = round(random.uniform(15.0, 90.0), 1)
    consistency = random.randint(50, 99)

    # 4. SAVE TO DATABASE
    new_record = AnalysisRecord(
        student_name=student_name,
        matric_no=matric_no,
        filename=file.filename,
        ai_score=ai_score,
        verdict=verdict,
        perplexity=perplexity,
        burstiness=burstiness,
        consistency=consistency
    )
    db.session.add(new_record)
    db.session.commit()

    return jsonify({
        "success": True,
        "score": ai_score,
        "verdict": verdict,
        "perp": perplexity,
        "burst": burstiness,
        "cons": consistency,
        "report_id": new_record.id
    })

# DASHBOARD DATA FEED
@app.route('/api/dashboard_data')
def dashboard_data():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 403
    
    records = AnalysisRecord.query.order_by(AnalysisRecord.timestamp.desc()).all()
    data = []
    for r in records:
        data.append({
            "id": r.id,
            "student_name": r.student_name,
            "matric_no": r.matric_no,
            "ai_score": r.ai_score,
            "verdict": r.verdict,
            "timestamp": r.timestamp.strftime('%Y-%m-%d %H:%M')
        })
    return jsonify(data)

# ADMIN OVERRIDE (DELETE RECORD)
@app.route('/delete/<int:id>', methods=['POST'])
def delete_record(id):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 403
        
    record = AnalysisRecord.query.get_or_404(id)
    try:
        db.session.delete(record)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to delete record."}), 500

if __name__ == '__main__':
    app.run(debug=True)