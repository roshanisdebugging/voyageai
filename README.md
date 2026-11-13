# 🌍 VoyageAI / Tour Guide Platform

An AI-powered travel planning and itinerary management platform built with a **FastAPI** backend, **PostgreSQL** relational database, and modern **React / TypeScript** frontend.

---

## 📌 Table of Contents
- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Authentication & Security Model](#authentication--security-model)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Local Setup & Installation](#local-setup--installation)
  - [1. Database Configuration](#1-database-configuration)
  - [2. Backend Setup](#2-backend-setup)
  - [3. Frontend Setup](#3-frontend-setup)
- [Database Schema & Maintenance](#database-schema--maintenance)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

---

## 🚀 Overview

The Tour Guide platform allows travelers to generate intelligent itineraries, manage accommodations, calculate trip budgets, and communicate with an AI travel assistant. User isolation is enforced at the database level using server-managed, 7-day persistent `HttpOnly` sessions.

---

## ✨ Key Features

1. **Secure Session-Based Authentication**:
   - Explicit signup (`Name`, `Email`, `Password`).
   - Secure server-side hashing with `bcrypt`.
   - 7-day persistent session managed via secure, `HttpOnly`, `SameSite=Lax` cookies.
   - Zero storage of auth tokens or sensitive identifiers in `localStorage`.

2. **Personalized Onboarding & Preferences**:
   - Travel styles, transport preferences, activity interests, and budget levels.
   - Flexible onboarding flow (fill details or skip).

3. **AI Trip Planner & Itinerary Builder**:
   - Day-by-day activity breakdown with places of interest.
   - Integrated travel logistics (stays, transport, and expenses).

4. **Dedicated AI Travel Assistant (Chat)**:
   - Persistent chat session isolated per user.
   - Contextual travel advice and itinerary adjustments.

5. **Multi-User Data Isolation**:
   - Strict session binding: Every endpoint extracts user identity from the server cookie (`voyageai_session`).
   - Prevents cross-user data leakage.

---

## 🏛 System Architecture

```text
[ Browser / Client (React + TS) ]
        │
        │ HTTP Requests (credentials: 'include')
        ▼
   [ FastAPI Backend ]
        │
        ├── Session Verification via SHA-256(voyageai_session)
        ├── Bcrypt Password Verification
        │
        ▼
   [ PostgreSQL Database ]
        ├── auth_users (Credentials & identities)
        ├── sessions (Active session tokens, hashed)
        ├── user_profiles (Personal information & onboarding state)
        ├── user_preferences (Travel choices & budget parameters)
        ├── trips & itineraries (Isolated travel plans)
        └── chat_messages (Personalized AI assistant history)
```

---

## 🔒 Authentication & Security Model

- **No Dummy Defaults**: Registration requires valid `name`, `email`, and `password`.
- **Database Hashing**: Passwords stored as one-way `bcrypt` hashes; session tokens stored as SHA-256 digests (`token_hash`).
- **Cookie Flags**:
  - `HttpOnly`: Prevents client-side JavaScript access (mitigating XSS).
  - `SameSite=Lax`: Mitigates CSRF attacks.
  - `Max-Age=604800`: 7-day session lifetime.
- **Client Handling**: Fetch requests use `credentials: 'include'` to pass cookies automatically. No user IDs are passed as query parameters (`?user_id=...`).

---

## 🛠 Tech Stack

- **Backend**: Python 3.10+, FastAPI, SQLAlchemy, Pydantic, Passlib (`bcrypt`), Uvicorn
- **Database**: PostgreSQL
- **Frontend**: React, TypeScript, Vite, Tailwind CSS
- **AI Engine**: LLM integrations for trip and itinerary generation

---

## 📋 Prerequisites

Before getting started, ensure you have the following installed on your machine:
- [Python 3.10+](https://www.python.org/downloads/)
- [Node.js 18+](https://nodejs.org/) and `npm`
- [PostgreSQL](https://www.postgresql.org/download/) running locally or accessible via remote URI
- [Git](https://git-scm.com/)

---

## ⚙️ Local Setup & Installation

### 1. Database Configuration

1. Start your PostgreSQL service.
2. Create a new database:
   ```sql
   CREATE DATABASE tourguide_db;
   ```

---

### 2. Backend Setup

1. Open a terminal and navigate to the `backend` directory:
   ```bash
   cd tour-guide/backend
   ```

2. Create and activate a Python virtual environment:
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux**:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. Install required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in `backend/`:
   ```env
   DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/tourguide_db
   SECRET_KEY=your_super_secret_session_key
   COOKIE_DOMAIN=localhost
   ENVIRONMENT=development
   ```

5. Initialize the database schema:
   ```bash
   python -c "from database import init_db; init_db()"
   ```

6. Start the FastAPI development server:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   *The API will be available at `http://localhost:8000` (Swagger docs: `http://localhost:8000/docs`).*

---

### 3. Frontend Setup

1. Open a new terminal and navigate to the frontend directory:
   ```bash
   cd tour-guide/frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Create a `.env` file in the `frontend` root:
   ```env
   VITE_API_BASE_URL=http://localhost:8000
   ```

4. Launch the frontend development server:
   ```bash
   npm run dev
   ```
   *The web client will open at `http://localhost:5173` (or the port specified by Vite).*

---

## 🗄 Database Schema & Maintenance

### Key Tables
- `auth_users`: Core user accounts (`id`, `email`, `password_hash`, `provider`, `status`).
- `sessions`: Active login sessions (`id`, `token_hash`, `user_id`, `expires_at`, `revoked_at`).
- `user_profiles`: User profile data (`user_id`, `first_name`, `last_name`, `onboarding_status`).
- `user_preferences`: Travel preferences (`travelStyles`, `dietaryPreferences`, `budgetLevel`).
- `trips` & `itineraries`: Trip details, days, and scheduled activities.
- `chat_messages`: Conversation threads with the assistant.

### Resetting / Wiping Test Data
To wipe all user data, sessions, and trips while keeping table definitions intact, run this script inside `backend/`:

```powershell
@'
from database import engine
from sqlalchemy import text

tables = [
    "chat_messages", "trip_expenses", "trip_transports", "trip_stays",
    "itinerary_activities", "itinerary_days", "itineraries", "trips",
    "user_preferences", "user_profiles", "sessions", "auth_users"
]

with engine.begin() as conn:
    for tbl in tables:
        try:
            conn.execute(text(f"TRUNCATE TABLE {tbl} CASCADE;"))
            print(f"Cleared: {tbl}")
        except Exception as e:
            print(f"Skipping {tbl}: {e}")

print("Database cleared successfully.")
'@ | Out-File -Encoding utf8 wipe_db.py; python wipe_db.py; Remove-Item wipe_db.py
```

---

## 📡 API Reference (Core Auth & User Flow)

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Register user with `name`, `email`, `password`. Sets 7-day session cookie. | No |
| `POST` | `/api/auth/login` | Authenticate using `email` and `password`. Issues 7-day session cookie. | No |
| `GET` | `/api/auth/me` | Validates session cookie and retrieves current user profile. | Yes (Cookie) |
| `POST` | `/api/auth/logout` | Revokes the current session and clears the cookie. | Yes (Cookie) |
| `POST` | `/api/user/preferences` | Save or update onboarding travel preferences. | Yes (Cookie) |
| `GET` | `/api/trips` | Returns all trips belonging to the authenticated user. | Yes (Cookie) |
| `GET` | `/api/chat/messages` | Returns chat history for the active user. | Yes (Cookie) |

---

## 🔧 Environment Variables Summary

Concierge intent routing uses a structured Flash-Lite classifier before paid
answer generation. See [cost guard configuration, tests and measured limitations](docs/COST_GUARD.md).

### Backend (`backend/.env`)
```env
DATABASE_URL=postgresql://<username>:<password>@<host>:<port>/<dbname>
SECRET_KEY=<random-32-character-secret>
ENVIRONMENT=development
COOKIE_DOMAIN=localhost
GEMINI_API_KEY=<gemini-api-key>
COST_GUARD_BACKEND=gemini
COST_GUARD_MODEL=gemini-3.5-flash-lite
```

### Frontend (`frontend/.env`)
```env
VITE_API_BASE_URL=http://localhost:8000
```

---

## ❓ Troubleshooting

1. **401 Unauthorized across all requests**:
   - Ensure your client fetch call includes `credentials: 'include'`.
   - Verify that your browser is not blocking third-party/localhost cookies.
   - Check if the session in the `sessions` table has expired or has a populated `revoked_at` timestamp.

2. **CORS / Cookie Rejection**:
   - In `backend/main.py`, verify `CORSMiddleware` configuration includes:
     - `allow_credentials=True`
     - Exact frontend origin (e.g., `["http://localhost:5173", "http://localhost:3000"]`, not wildcard `*`).

3. **Database Connection Errors**:
   - Verify PostgreSQL service is active (`Get-Service postgresql*` on Windows).
   - Ensure the database name in `DATABASE_URL` matches the created database.
