# ProAuth (Django + Next.js)

This project provides a JWT cookie-based auth backend in Django and a polished Next.js frontend with signup, login, and password reset flows.

## Backend

1. Create a virtual environment and install dependencies:

```bash
cd backend
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

2. Create `.env` from `.env.example` and fill in your SMTP credentials.

3. Run migrations and start the server:

```bash
python manage.py migrate
python manage.py runserver 8000
```

To run with WebSockets (recommended for live rooms), use Daphne:

```bash
cd backend
daphne -b 0.0.0.0 -p 8000 backend.asgi:application
```

## Frontend

1. Install dependencies and start Next.js:

```bash
cd frontend
npm install
npm run dev
```

2. Create `.env.local` from `.env.local.example` if you need to change the API base URL.

## Endpoints

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/logout/`
- `POST /api/auth/token/refresh/`
- `POST /api/auth/password-reset/`
- `POST /api/auth/password-reset/confirm/`
- `GET /api/auth/me/`
- `POST /api/rooms/create/`
- `POST /api/rooms/join/`

## Live Drawing Rooms

- WebSocket endpoint: `ws://localhost:8000/ws/rooms/<CODE>/`
- Rooms are capped at 8 players.
- Uses Redis channel layers via `REDIS_URL` (configure in `.env`).

## Notes

- JWTs are stored in HttpOnly cookies (`access_token`, `refresh_token`).
- For production, set `JWT_COOKIE_SECURE=True`, update `ALLOWED_HOSTS`, and use HTTPS.
