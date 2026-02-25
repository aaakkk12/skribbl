# Online Drawing Game (Django + Next.js)

Real-time multiplayer drawing game with guest onboarding:
- Home page: choose character + username
- Next: room lobby with `Create Room`, `Join Room`, `Join Random Room`
- Live gameplay via WebSocket + Redis

## Stack
- `backend/`: Django, DRF, Channels, Redis, Daphne
- `frontend/`: Next.js App Router

## Local Setup
1. Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver 8000
```

2. Frontend
```bash
cd frontend
npm install
npm run dev -- -p 3000
```

## Production (AWS Ubuntu + Domain)
Use these concrete values for `onlinedrawinggame.online`:

Backend `.env` (example):
```env
ENVIRONMENT=production
DEBUG=False
DJANGO_SECRET_KEY=<50+ char secret>
ALLOWED_HOSTS=onlinedrawinggame.online,www.onlinedrawinggame.online,<EC2_PUBLIC_IP>

CORS_ALLOWED_ORIGINS=https://onlinedrawinggame.online
CSRF_TRUSTED_ORIGINS=https://onlinedrawinggame.online
WS_ALLOWED_ORIGINS=https://onlinedrawinggame.online

DB_ENGINE=postgres
DB_NAME=app
DB_USER=app
DB_PASSWORD=<strong_password>
DB_HOST=127.0.0.1
DB_PORT=5432

REDIS_URL=redis://127.0.0.1:6379/0
USE_REDIS_CACHE=True
CACHE_URL=redis://127.0.0.1:6379/1

JWT_COOKIE_SECURE=True
GUEST_DEVICE_COOKIE=guest_device_id
GUEST_DEVICE_COOKIE_MAX_AGE=31536000
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
EMPTY_ROOM_DELETE_MINUTES=1
```

Recommended runtime:
- Daphne for Django ASGI (port `8000`)
- Next.js production server (port `3000`)
- Nginx reverse proxy (`80/443`)
- Certbot TLS certificate
- Redis + Postgres system services
- `systemd` services for backend/frontend auto-restart

### Zero-to-live on EC2 (GitHub pull flow)
1. Push code to GitHub.
2. SSH into Ubuntu EC2 and clone once for bootstrap:
```bash
git clone git@github.com:YOUR_USER/YOUR_REPO.git ~/bootstrap-onlinedrawinggame
cd ~/bootstrap-onlinedrawinggame
```
3. Run one-time bootstrap:
```bash
sudo bash deploy/scripts/bootstrap_ubuntu.sh main git@github.com:YOUR_USER/YOUR_REPO.git
```
4. Update env files:
- `/etc/onlinedrawinggame/backend.env`
- `/etc/onlinedrawinggame/frontend.env`
5. Run deploy:
```bash
sudo bash /srv/onlinedrawinggame/app/deploy/scripts/deploy_pull.sh main
```
6. Issue TLS cert:
```bash
sudo bash /srv/onlinedrawinggame/app/deploy/scripts/setup_certbot.sh your-email@example.com
```

Detailed guide: `deploy/README.md`

## WebSocket Endpoints
- Lobby: `/ws/lobby/`
- Room: `/ws/rooms/<CODE>/`

## Notes
- Guest identity is session-based (`/api/auth/guest-session/`) and auto-creates/updates player profile.
- Browser localStorage keeps only username + character; stable guest device identity is handled via secure cookie.
- Random join endpoint: `/api/rooms/join-random/` (joinable public live rooms only).
- Room cleanup removes empty rooms quickly and also clears associated Redis room state/history keys.
