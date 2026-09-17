# Deploying (Ubuntu + Docker)

This is the one deployment path this repo supports: your own Ubuntu
server with a static IP, running the app in Docker behind an Nginx
reverse proxy. (Earlier drafts covered Render, Fly.io, AWS, and Windows/
IIS too — dropped in favor of committing to this one.)

## 1. Read this first: constraints of the current design

- **Conversation memory (`graph.py`'s `_CONVERSATIONS`) is an in-memory,
  process-local dict.** It lives only inside one running process. Run
  exactly one container — more than one means users randomly land on
  different conversation histories, with no way to reconcile them. This
  isn't something Docker or the compose file can fix; it would need an
  external store (Redis or similar) to actually support multiple
  instances, which is out of scope here.
- **The SQLite file persists correctly** as long as you use the volume
  setup below (`./data` bind-mounted, `DATABASE_URL`/`SQLITE_DATA_DIR`
  pointed at it) — that part **is** handled, see section 3.

## 2. Build & test the image locally first

```bash
docker compose up -d --build
docker compose logs -f   # confirm it started cleanly, then Ctrl+C
curl http://127.0.0.1:8000/health
```

`.env` (copy `.env.example` → `.env` and fill in `API_KEY`) is read by
`docker-compose.yml` via `env_file` and never baked into the image or
committed — the Gemini key stays out of both the image and git history.

## 3. Why the compose file is shaped this way

```yaml
environment:
  - DATABASE_URL=sqlite:////data/accounting.db
  - SQLITE_DATA_DIR=/data
volumes:
  - ./data:/data
```

`accounting.db` **is committed to this repo** (`.gitignore` has an
explicit exception for it) — it's this project's seed/demo chart of
accounts, not a secret, and the whole point of the setup below depends on
it actually being present after a `git clone`, not just on your local
machine. `entrypoint.sh` copies it into `/data/accounting.db` the first
time that path is empty, then leaves it alone on every later boot — so
the bind-mounted `./data` directory on the host is what actually persists
across `docker compose up`/`down`/redeploys, not the image.

Earlier drafts of this file bind-mounted `accounting.db` directly
(`-v ./accounting.db:/app/accounting.db`) instead of a directory. That's
broken on a genuine fresh clone: Docker creates an empty *directory* at
the mount point when the source file doesn't exist on the host yet, which
it wouldn't if `accounting.db` were still gitignored. Caught this by
actually simulating a fresh clone (`git archive` into an empty directory,
no local untracked files carried over) rather than testing against a
working copy that already happened to have the file on disk.

## 4. Deploy on the server

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out/in once for this to take effect

git clone <this-repo-url> smart-accounting
cd smart-accounting
cp .env.example .env   # edit in your real API_KEY

docker compose up -d --build
docker compose logs -f   # confirm it started cleanly and seeded /data, then Ctrl+C
```

To update after a `git pull`:
```bash
git pull
docker compose up -d --build
```
`./data/accounting.db` isn't touched by this — only by deleting the `data/`
directory yourself.

## 5. Put Nginx in front of it

The app only ever binds `127.0.0.1:8000` (see `docker-compose.yml`'s
`ports:`) — it is never directly reachable from the internet. Nginx is
what's actually public, terminating TLS and reverse-proxying to the app.
`deploy/nginx.conf` has this ready to go.

```bash
sudo apt update && sudo apt install -y nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/smart-accounting
# edit server_name in that file to your domain or the server's static IP first
sudo ln -s /etc/nginx/sites-available/smart-accounting /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx   # skip if you have no domain yet
sudo certbot --nginx -d your-domain.example

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # 80 + 443 - port 8000 is never opened to the internet
sudo ufw enable
```

Open `http://<your-static-ip>/` (or your domain, once DNS points at it and
you've run certbot, `https://your-domain.example/`).

## 6. What's in the repo for this

| File | Purpose |
| --- | --- |
| `Dockerfile` | Python 3.11-slim, installs `requirements.txt`, runs `entrypoint.sh` on port 8000. |
| `entrypoint.sh` | Seeds `SQLITE_DATA_DIR` from the image's bundled `accounting.db` on first boot if that path is empty, then execs uvicorn. |
| `docker-compose.yml` | `docker compose up -d --build` — builds the image, mounts `./data` for the DB, reads `.env` for `API_KEY`, binds the app to `127.0.0.1` only, `restart: unless-stopped`. |
| `deploy/nginx.conf` | Reverse proxy: real HTTPS via Certbot, the app itself never directly exposed. |
| `.env.example` | Template for `.env` — copy it and fill in `API_KEY`. |
| `.dockerignore` | Keeps `.venv`, `.git`, `.env`, `tests/` out of the image. |
| `.gitattributes` | Forces LF line endings on `entrypoint.sh` / `deploy/nginx.conf` — a CRLF shebang or config line breaks parsing on the Linux server if this repo is checked out on Windows without it. |
| `accounting.db` | This repo's seed/demo chart of accounts, committed on purpose — see section 3. |
