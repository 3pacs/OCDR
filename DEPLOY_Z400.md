# z400 — Permanent OCMRI App Host: Deployment Runbook

Goal: z400 = always-on Linux host for the OCMRI/MRI apps (OCDR billing first; others slot in).

Current role boundary: keep z400 focused on the OCDR Docker stack. Do not run GRID
permutation/gem-hunter workers or llama/vision services here. Alien is the preferred
always-on node for Excel/document ingestion and interactive document access once
SSH/key access is configured.
Light box, **no GPU needed** (GPU work stays on the cluster). RAM note: BIOS v1.06 clamps to
**3.8 GB** — Postgres+FastAPI fits but is tight; flash BIOS **v3.61** to unlock 16 GB when convenient.

## 0. Base OS (after Ubuntu Server install, erase-disk)
```bash
sudo apt update && sudo apt -y upgrade
# Docker + compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # then log out/in (or: newgrp docker)
sudo systemctl enable --now docker
# SSH (fresh install wiped authorized_keys — re-add ocr-node's key so Claude can reach it)
sudo apt -y install openssh-server
mkdir -p ~/.ssh && echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJpUcgkZbDy1i7MLkuAnvVmOEBIXcDpAI5BKKtcIKQHi anikd@ocr-node' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
# Tailscale (so it's reachable as z400.<tailnet>)
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
# gh (for 3pacs private repos)
sudo apt -y install gh && gh auth login
```

## 1. Get the OCDR app
```bash
mkdir -p ~/apps && cd ~/apps
git clone https://github.com/3pacs/OCDR.git && cd OCDR
git checkout claude/billing-reconciliation-system-QOXpY   # branch w/ F-10 physician_statements.py (see NOTE)
cp .env.example .env
# edit .env: set a strong POSTGRES_PASSWORD + SECRET_KEY; POSTGRES_PORT=5432 (free on z400 — no grid_db here),
#            BACKEND_PORT=8000, FRONTEND_PORT=3000, ENVIRONMENT=production
```

## 2. Bring it up
```bash
docker compose up -d            # builds backend+frontend, starts postgres (first build ~few min)
docker compose ps
curl -s localhost:8000/health   # {"status":"healthy",...}
```

## 3. Load current data
```bash
# Get the CURRENT Excel onto z400 (from ANIK over Tailscale, or the RIS SMB share):
#   scp "OCMRI with LLM.xlsx" anikd@z400:~/apps/OCDR/data/excel/
curl -s -X POST localhost:8000/api/import/excel -F 'file=@"data/excel/OCMRI with LLM.xlsx"'
curl -s localhost:8000/api/import/status
```
NOTE: `billing_records` is a snapshot of the Excel "Current" sheet — only as fresh as the last import + the Excel itself. See memory [[check-data-freshness-before-presenting]].

## 4. Make it permanent
- compose already sets `restart: unless-stopped`; `docker` enabled on boot (step 0) → survives reboots/power-loss.

## 5. Autonomous freshness (the north-star bit)
- Cron/APScheduler on z400 to **re-import the current Excel** on a schedule (keep data current), and run **F-10 physician statements** monthly (Jhangiani 5th). Wire as a Hermes capability so it runs untouched (zero Claude tokens). See [[reference-ocdr-billing-app]] (F-10) + [[ocmri-hermes]].

## 6. Other MRI apps → permanent home here
Same pattern — clone the Linux-friendly ones into `~/apps`: `OCMRI TOPAZ CLIENT` (python), `imaging-scheduler`, `scansnap-headless`, `OCMRI_forensics`. `EOB-Finder` has a Windows `.exe` — keep on a Windows box or port. (Check which exist as 3pacs repos: `gh repo list 3pacs`.)

## 7. Node role boundaries
- z400: OCDR Docker stack only (`postgres`, `backend`, `frontend`) plus lightweight support services.
- Do not run GRID permutation/gem-hunter workers or llama/vision services on z400.
- Alien: Excel/document ingestion and document-access workflows. Do not split OCDR Postgres/backend/frontend across Alien unless the entire stack is intentionally moved.

## NOTES / gotchas
- **F-10 `backend/app/revenue/physician_statements.py` is currently UNCOMMITTED on ANIK** — commit+push to the branch (or copy the file to z400) so the clone includes it. PDF render needs `reportlab` (not yet in `requirements.txt` — add it, or render host-side per `data/exports/render_stmt.py`).
- `fee_schedule` table has heavy duplicate rows — dedupe in queries (`MAX(expected_rate) GROUP BY payer_code,modality`).
- On ANIK we ran postgres on host port **5433** to avoid `grid_db` (TimescaleDB) on 5432; on z400, **5432 is free** — use the default.
