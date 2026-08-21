# Acadetect — AI Project Scanner

An AI-powered academic integrity tool built for the **Department of Computer Engineering, University of Benin**. The platform scans final-year project submissions (PDF/DOCX) for AI-generated content using stylometric analysis, providing administrators with real-time analytics and students with instant feedback.

## 🌐 Live Demo

| Service | URL |
|---------|-----|
| **Student Portal** | [cpe-portal.vercel.app](https://cpe-portal.vercel.app) |
| **Backend API** | [cpe-portal-backend.onrender.com](https://cpe-portal-backend.onrender.com) |

## ✨ Features

- **AI Detection Engine** — Local stylometric **logistic model** (no external API) trained on a public 44k-essay dataset; evaluates sentence uniformity, lexical diversity, phrase repetition, templated language, punctuation, and more
- **PDF & DOCX Support** — Extracts and analyzes text from uploaded project files
- **Duplicate Submission Guard** — Prevents multiple submissions per matriculation number
- **Admin Dashboard** — JWT-protected panel with real-time charts, submission history, and override controls
- **Printable Report** — Generates an official AI scan report per student for supervisor review

## 🏗️ Architecture

```
cpe_portal/
├── frontend/                  # Static HTML/CSS/JS — hosted on Vercel
│   ├── index.html             # Student upload portal
│   ├── login.html             # Admin login page
│   ├── dashboard.html         # Admin analytics dashboard
│   ├── report.html            # Printable scan report
│   ├── static/
│   │   ├── css/style.css      # Global styles
│   │   └── js/
│   │       ├── config.js      # Backend URL configuration
│   │       ├── portal.js      # Upload & analysis logic
│   │       └── dashboard.js   # Dashboard rendering & chart logic
│   └── vercel.json            # Vercel routing config
│
├── backend/                   # Flask API — hosted on Render
│   ├── main.py                # Flask app (routes, models, CORS, JWT)
│   ├── requirements.txt       # Python dependencies
│   └── app/
│       └── stylometry/
│           ├── engine.py      # AI detection engine (trained logistic model)
│           ├── train.py       # Re-calibrate weights on labelled data
│           └── weights.json   # Fitted model weights (auto-loaded)
│
└── render.yaml                # Render deployment blueprint
```

## 🔧 Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML5, CSS3, Vanilla JavaScript, Chart.js |
| Backend | Python 3.12, Flask, Flask-CORS, Flask-JWT-Extended |
| Database | PostgreSQL (Render) / SQLite (local dev) |
| AI Engine | Stylometric logistic model (pure Python, trained on 44k essays) |
| File Parsing | PyPDF2, python-docx |
| Hosting | Vercel (frontend), Render (backend + database) |

## 🚀 Local Development

### Prerequisites

- Python 3.12+
- pip

### Backend

```bash
cd backend
pip install -r requirements.txt
python main.py
```

The API will start at `http://localhost:5000`.

### Frontend

Update `frontend/static/js/config.js` to point to your local backend:

```js
const BACKEND_URL = "http://localhost:5000";
```

Then serve the frontend with any static server (e.g., VS Code Live Server, or Python):

```bash
cd frontend
python -m http.server 5500
```

Visit `http://localhost:5500`.

## 📡 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/login` | — | Admin login (returns JWT) |
| `POST` | `/api/analyze` | — | Upload & analyze a project file |
| `GET` | `/api/dashboard_data` | JWT | Fetch all submission records |
| `GET` | `/api/report/:id` | — | Fetch a single report by ID |
| `POST` | `/api/delete/:id` | JWT | Delete a submission record |
| `GET` | `/api/health` | — | Health check |

## 🔐 Default Admin Credentials

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `uniben2026` |

> ⚠️ These are hardcoded defaults. For production use, implement proper user management with hashed passwords.

## 📝 How the AI Detection Works

The engine extracts ~9 length-robust **stylometric features** from the text and combines them with a **logistic-regression model** — no external AI API and no heavy ML framework (pure Python). Features include:

1. **Sentence uniformity** — AI text tends toward consistent sentence lengths
2. **Lexical diversity (MATTR)** — length-robust vocabulary richness
3. **Phrase repetition** — repeated bigrams/trigrams and word reuse
4. **Templated language** — over-produced transitions/buzzwords ("furthermore", "delve", "pivotal", …)
5. **Opener diversity, punctuation, hapax rate, function-word balance**

The weights are **trained, not guessed** — fitted on the public [DAIGT V2](https://www.kaggle.com/datasets/thedrcat/daigt-v2-train-dataset) dataset (~44k human/AI essays), scoring **77.8% held-out accuracy** (precision 79%, recall 77%). Re-calibrate anytime on your own labelled samples:

```bash
cd backend/app/stylometry
python train.py path/to/data.csv     # CSV with text,label columns (1=AI, 0=human)
python train.py path/to/folder       # or folders: human/*.txt + ai/*.txt
```

This writes `weights.json`, which the engine auto-loads on startup. The resulting score (0–100%) is classified as:
- 🟢 **Human Written** (< 42%)
- 🟡 **Mixed / needs review** (42–68%)
- 🔴 **AI Generated** (> 68%)

> **Disclaimer:** A statistical estimate from stylometric patterns — a flag for human review, **not** proof of AI authorship.

## 📄 License

This project was developed as a final-year project for the Department of Computer Engineering, University of Benin.

---

*Built with ❤️ for academic integrity.*
