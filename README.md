# ApplyPilot

ApplyPilot is a single-user autonomous job application and outreach platform built with FastAPI, React, and MongoDB. It streamlines off-campus HR outreach by:
- Importing HR contact lists via CSV.
- Automatically matching target roles against your tailored role profiles and active resumes.
- Generating hyper-personalized outreach emails using modern LLMs (Gemini, OpenAI, Anthropic).
- Sending cold applications directly from your own Gmail account with human-in-the-loop approval or controlled autopilot modes.
- Tracking replies, reminders, and follow-ups.

---

## Architecture & Features

- **Single-User Security:** Designed for personal use with env-configured owner authentication (`OWNER_EMAIL`, `OWNER_PASSWORD_HASH`), HttpOnly SameSite=Lax session cookies, and brute-force lockout protection.
- **Direct Multi-Provider LLM Interface:** Native structured outputs with Google Gemini (`gemini-2.5-flash` default), OpenAI (`gpt-4o`), and Anthropic (`claude-3-5-sonnet`). Configurable concurrency limits and automatic retry with exponential backoff.
- **Pluggable File Storage:** Local filesystem storage (`./data/uploads`) with directory traversal protection, or S3/Cloudflare R2 cloud storage.
- **In-Process Automation Scheduler:** Built-in APScheduler running inside FastAPI lifespan with MongoDB distributed lease locks for safe concurrency.
- **Least-Privilege Gmail OAuth:** Scoped strictly to `gmail.send` and `gmail.readonly` for sending outreach and monitoring responses.
- **Safe by Default:** `DRY_RUN=true` simulation mode prevents accidental email dispatch during testing and development.
- **Bulk Pipeline with Quality Guardrails:** Intelligent duplicate prevention, word-count caps, placeholder rejection, and rotating opening styles to avoid robotic emails.

---

## Prerequisites

- **Python:** 3.11+
- **Node.js:** 18+ and `yarn`
- **MongoDB:** 7.0+ (running locally or via Docker)

---

## Local Development Setup

### 1. Clone & Setup Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install production and development dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment variables
cp .env.example .env
```

#### Generating Required Secrets

1. **Password Hash:**
   ```bash
   python ../scripts/hash_password.py
   ```
   Paste the generated hash into `OWNER_PASSWORD_HASH` in `.env`.

2. **Session Secret:**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Paste into `SESSION_SECRET` in `.env`.

3. **OAuth Encryption Key:**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Paste into `APP_ENCRYPTION_KEY` in `.env`.

4. **LLM API Key:**
   Set `GEMINI_API_KEY` (or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`).

### 2. Start Backend Server

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

Backend will be available at `http://localhost:8000`. Health check endpoint: `GET http://localhost:8000/api/health`.

### 3. Setup Frontend

In a separate terminal:

```bash
cd frontend
yarn install
yarn start
```

Frontend will run at `http://localhost:3000`.

---

## Running with Docker Compose

You can spin up MongoDB, the backend, and the frontend with a single command:

```bash
# Ensure your backend/.env is configured with your secrets and LLM key
docker compose up --build
```

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000/api`
- MongoDB: `localhost:27017`

---

## Running Tests

All automated tests target an isolated test database (`applypilot_test`) that is automatically cleaned up after test runs:

```bash
# Run full backend test suite
pytest backend/tests/ -v

# Run frontend build check
cd frontend
yarn build
```

---

## Chrome Extension Setup

ApplyPilot includes a Chrome extension for capturing job descriptions from job boards into your pipeline:

1. Open Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** in the top right.
3. Click **Load unpacked** and select the `extension/` directory.
4. Copy your Extension API Token from the Settings page in the ApplyPilot web dashboard.
