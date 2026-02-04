<div align="center">

# Skribbl-Style Live Drawing Game (Django + Next.js)

![Status](https://img.shields.io/badge/status-active-22c55e?style=for-the-badge)
![Frontend](https://img.shields.io/badge/Next.js-14-0ea5e9?style=for-the-badge)
![Backend](https://img.shields.io/badge/Django-5-22c55e?style=for-the-badge)
![Realtime](https://img.shields.io/badge/Realtime-WebSockets-f97316?style=for-the-badge)
![Auth](https://img.shields.io/badge/Auth-JWT%20Cookies-8b5cf6?style=for-the-badge)

</div>

Real-time multiplayer drawing + guessing game with JWT cookie auth, WebSockets, lobby updates, and an admin control panel.

---

## Features
- JWT cookie auth (signup, login, reset password).
- Live drawing rooms with chat, hints, rounds, scoring, and kick votes.
- Room privacy: open or private (password protected).
- Lobby with real-time room list and player counts.
- Admin panel for room control and user management (ban/archive/restore).

---

## Project Structure
- `backend/` Django + Channels + Redis.
- `frontend/` Next.js App Router UI.

---

## Backend Setup
1. Create venv + install deps:
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Create `.env` from `.env.example` and fill credentials:
```bash
copy .env.example .env
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Start server:
```bash
python manage.py runserver 8000
```

For WebSockets (recommended), use Daphne:
```bash
cd backend
daphne -b 0.0.0.0 -p 8000 backend.asgi:application
```

---

## Frontend Setup
1. Install deps and run:
```bash
cd frontend
npm install
npm run dev -- -p 3000
```

2. Optional: `.env.local` (if you need a different API URL).

---

## Admin Panel
- URL: `http://localhost:3000/admin`
- Credentials come from `.env`:
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=123
```
Capabilities:
- List rooms and toggle open/private.
- Delete rooms (broadcasts close event).
- List users, send reset links, ban, archive, restore.

---

## Room Privacy
- Create room with `open` or `private`.
- Private rooms require a password for join.
- Lobby shows `Open` / `Private`.

---

## WebSocket Endpoints
- Rooms: `ws://localhost:8000/ws/rooms/<CODE>/`
- Lobby: `ws://localhost:8000/ws/lobby/`

---

## Notes
- JWT cookies: `access_token` + `refresh_token` are HttpOnly.
- Redis required for Channels: set `REDIS_URL` in `.env`.
- If you see SQLite `disk I/O error`, pause OneDrive sync or move project outside OneDrive before running migrations.

---

## Production Tips
- Set `JWT_COOKIE_SECURE=True` and use HTTPS.
- Configure `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`.
- Replace default admin creds in `.env`.

---

## Release Checklist
1. Verify `.env` is not committed; only `.env.example` is in git.
2. Update `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`.
3. Set `JWT_COOKIE_SECURE=True` and HTTPS termination.
4. Set strong `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
5. Ensure Redis is running and `REDIS_URL` is correct.
6. Run `python manage.py migrate` on production DB.
7. Build frontend: `npm run build` and run with `npm run start`.
