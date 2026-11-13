# Cruiser — Docker Deployment Guide

Full-stack 3-tier containerized deployment:
- **2 Dockerfiles**:
  - `Dockerfile` (Frontend: React + Vite + Nginx)
  - `backend/Dockerfile` (Backend: FastAPI + Python 3.11)
- **1 Docker Compose (`docker-compose.yml`)** with **3 services on the same internal network**:
  - `frontend` (Port `80:80` forwarded to host — **ONLY public port**)
  - `backend` (Internal port `8000` — private to Docker network)
  - `db` (PostgreSQL 16 on internal port `5432` — private to Docker network)

---

## Network & Security Architecture

```
                                [ Public Internet / Users ]
                                             │
                                      ( Host Port 80 )
                                             ▼
═══════════════════════════════════════════════════════════════════════════════════════════════
  DOCKER NETWORK: cruiser-network (Bridge)
═══════════════════════════════════════════════════════════════════════════════════════════════
        ┌─────────────────────────────────────────────────────────┐
        │                    cruiser-frontend                     │
        │                       (Nginx SPA)                       │
        │               [ONLY PORT FORWARDED TO HOST]             │
        └──────────────┬───────────────────────────┬──────────────┘
                       │                           │
          http://backend:8000/api/                 │ ws://backend:8000/ws/
                       ▼                           ▼
        ┌─────────────────────────────────────────────────────────┐
        │                     cruiser-backend                     │
        │                   (FastAPI on :8000)                    │
        │              [INTERNAL ONLY - NO HOST PORT]             │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     │ postgresql://db:5432/cruiser
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │                       cruiser-db                        │
        │                   (PostgreSQL :5432)                    │
        │              [INTERNAL ONLY - NO HOST PORT]             │
        └─────────────────────────────────────────────────────────┘
```

---

## 1. Launch All 3 Services

From the project root:

```bash
# 1. Build and start frontend, backend, and postgres database:
docker compose up -d --build

# 2. View live logs:
docker compose logs -f

# 3. View status of all 3 services:
docker compose ps

# 4. Stop all services:
docker compose down
```

### Accessing the App:
- **Web Application**: Open `http://<server-ip>/` in your browser.
- All `/api/*` and `/ws/*` calls are routed internally by Nginx to the backend container.
- Neither the backend nor the database expose ports to the outside world.

---

## 2. Database & Environment Configuration

In `docker-compose.yml`, the backend automatically connects to the PostgreSQL container over the Docker network using:
```
DATABASE_URL=postgresql://postgres:postgres@db:5432/cruiser
```
All tables are automatically created on first boot by the backend ORM sync.

To add your Gemini API Key or other credentials, create/update `backend/.env`:
```env
GEMINI_API_KEY=your_key_here
GOOGLE_MAPS_API_KEY=your_key_here
```
