# AWS Ubuntu Deploy Guide

This folder contains production-ready templates for:
- `systemd` services
- `nginx` reverse proxy
- `certbot` TLS
- pull-based deploy scripts (GitHub -> EC2)

## Folder Map
- `systemd/onlinedrawinggame-backend.service`
- `systemd/onlinedrawinggame-frontend.service`
- `nginx/onlinedrawinggame.online.conf`
- `env/backend.env.production.example`
- `env/frontend.env.production.example`
- `scripts/bootstrap_ubuntu.sh`
- `scripts/deploy_pull.sh`
- `scripts/setup_certbot.sh`

## 0) DNS
Before TLS, point both records to your EC2 public IP:
- `onlinedrawinggame.online` (A record)
- `www.onlinedrawinggame.online` (A record)

## 1) First-time server bootstrap
If app is not cloned yet on EC2, run:

```bash
git clone git@github.com:YOUR_USER/YOUR_REPO.git ~/bootstrap-onlinedrawinggame
cd ~/bootstrap-onlinedrawinggame
```

Then run bootstrap as root:

```bash
sudo bash deploy/scripts/bootstrap_ubuntu.sh main git@github.com:YOUR_USER/YOUR_REPO.git
```

This installs OS packages, clones app to `/srv/onlinedrawinggame/app`, configures nginx/systemd templates, and creates env files in `/etc/onlinedrawinggame/`.

## 2) PostgreSQL setup (one-time)
Create DB and user:

```bash
sudo -u postgres psql
CREATE DATABASE onlinedrawinggame;
CREATE USER onlinedrawinggame WITH ENCRYPTED PASSWORD 'change-this-password';
GRANT ALL PRIVILEGES ON DATABASE onlinedrawinggame TO onlinedrawinggame;
\q
```

## 3) Fill env files
Edit:
- `/etc/onlinedrawinggame/backend.env`
- `/etc/onlinedrawinggame/frontend.env`

Use templates from `deploy/env/` and set real secrets/passwords.

## 4) Deploy latest code from GitHub
Any time after pushing to GitHub:

```bash
sudo bash /srv/onlinedrawinggame/app/deploy/scripts/deploy_pull.sh main
```

This pulls latest code, installs deps, runs migrations, collects static files, builds Next.js, and restarts services.

## 5) Enable HTTPS (Certbot)
After DNS is resolving:

```bash
sudo bash /srv/onlinedrawinggame/app/deploy/scripts/setup_certbot.sh your-email@example.com
```

## 6) Health checks
```bash
sudo systemctl status onlinedrawinggame-backend.service
sudo systemctl status onlinedrawinggame-frontend.service
sudo systemctl status nginx
curl -I https://onlinedrawinggame.online
```
