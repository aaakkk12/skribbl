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

## 7) Enable auto deploy with GitHub Actions (CI/CD)
This repo includes `.github/workflows/production-cicd.yml`.

It will:
- Run CI on push to `main` (`manage.py check`, frontend lint, frontend build)
- SSH into your EC2 and run:
  - `sudo bash /srv/onlinedrawinggame/app/deploy/scripts/deploy_pull.sh main`

### 7.1 Add GitHub repository secrets
In GitHub: `Settings -> Secrets and variables -> Actions -> New repository secret`

Required:
- `PROD_HOST` (example: `onlinedrawinggame.online` or your EC2 public IP)
- `PROD_SSH_USER` (example: `ubuntu`)
- `PROD_SSH_PRIVATE_KEY` (private key content for SSH login)

Optional:
- `PROD_SSH_PORT` (default `22`)

### 7.2 Allow passwordless sudo for deploy command
On EC2, add a restricted sudoers rule for the SSH user used by the workflow.
If your SSH user is `ubuntu`:

```bash
echo 'ubuntu ALL=(root) NOPASSWD:/bin/bash /srv/onlinedrawinggame/app/deploy/scripts/deploy_pull.sh main' | sudo tee /etc/sudoers.d/onlinedrawinggame-cicd
sudo chmod 440 /etc/sudoers.d/onlinedrawinggame-cicd
sudo visudo -cf /etc/sudoers.d/onlinedrawinggame-cicd
```

### 7.3 First run
- Push to `main`, or
- Trigger manually from `Actions -> Production CI/CD -> Run workflow`
