# Deploying

This covers containerizing the app and putting it on a real host for
**testing/demo purposes**. Two free options are covered step by step,
pick based on what you care about more:

- **[Render](#3-render-free-no-payment-method-at-all)** — genuinely no
  payment method required, ever, confirmed directly from Render's own
  docs. Trade-off: free web services have no persistent disk, so the DB
  resets to this repo's seed data every time the service redeploys,
  restarts, or spins down from 15 minutes of inactivity. Good fit for
  "here's a demo link," not for data you need to keep between sessions.
- **[Fly.io](#4-flyio-free-payment-method-required-for-verification)** —
  also free, and the DB actually persists (a real mounted volume, not
  reset on restart), but Fly.io requires a payment method on file to
  verify you're not a bot, even though it won't be charged within the
  free allowance.

AWS is kept further down as a third alternative.

Nothing here deploys on its own — these are the files and the exact
commands, for you to run yourself (account creation and anything
requiring a login/payment method has to happen on your end regardless).

## 1. Read this first: constraints of the current design

Two things about how the app is built right now matter a lot once it leaves
your laptop:

- **SQLite (`accounting.db`) is a single file.** It is not a shared
  database — if more than one container instance runs, each gets its own
  independent copy, and nothing is synced between them. `database.py` now
  reads its path from a `DATABASE_URL` env var (falling back to the old
  relative `./accounting.db` if unset), and `entrypoint.sh` seeds that path
  from the image's bundled `accounting.db` the first time it's empty — so
  on a host that mounts a **persistent volume** at that path (Fly.io, or a
  bind-mounted EC2 directory), your data survives redeploys/restarts. On a
  host with no persistent volume (App Runner, a plain `docker run` with no
  `-v`), it's still reset every time the container restarts.
- **Conversation memory (`graph.py`'s `_CONVERSATIONS`) is an in-memory,
  process-local dict.** It lives only inside one running process, with no
  volume that could fix this the way it fixes the DB. A second instance
  (or a restart of the same one) has no idea a given `conversation_id`
  ever existed.

Neither of these is a bug to fix before testing — they're documented,
known limitations (see `README.md`). But they mean: **run exactly one
instance**, and — unless you're on a host with the persistent volume set up
— expect the DB and all conversation history to reset on every
redeploy/restart. That's fine for demoing Rima to a client; moving past it
for real would mean an external DB (Postgres) and an external store for
conversation state (Redis/similar) — a real follow-up, not part of this.

## 2. Build & test the image locally first

```bash
docker build -t smart-accounting-rima .
docker run -p 8000:8000 -e API_KEY=your-gemini-api-key smart-accounting-rima
```

Open `http://localhost:8000/chat` and talk to Rima before touching any
hosting platform — confirms the container itself is correct, independent
of anything platform-specific. This run has no volume mounted, so it
behaves like the pre-`DATABASE_URL` version: `accounting.db` baked into
the image, reset on every `docker run`.

To also test the persistent-volume path locally (what Fly.io does), mount
a named Docker volume and point the app at it the same way `fly.toml`
does:

```bash
docker run -p 8000:8000 -e API_KEY=your-gemini-api-key \
  -e DATABASE_URL=sqlite:////data/accounting.db \
  -e SQLITE_DATA_DIR=/data \
  -v smart_accounting_data:/data \
  smart-accounting-rima
```

First run seeds `/data/accounting.db` from the image's bundled copy (check
the logs for the "Seeded ..." line); stop and re-run the same command and
your data — including anything you added through the running app — is
still there, because it's reading from the named volume, not the image.

`.env` **is** excluded from the image on purpose — the Gemini `API_KEY`
must never be baked into an image that might get pushed to a registry.
Always pass it as a runtime environment variable, as above.

## 3. Render (free, no payment method at all)

`render.yaml` in the repo (a Render "Blueprint") already declares the
service — Docker build from this repo's `Dockerfile`, free plan, health
check at `/health`. Render's own docs confirm the free plan needs no
payment method, ever; the trade-off is no persistent disk, so treat this
as "always resets to this repo's committed `accounting.db`," not
somewhere to leave data you want to keep.

1. **Sign up** at <https://render.com> — GitHub/GitLab/email, no card.
2. **Push this repo to GitHub** if it isn't already there (Render deploys
   from a connected repo, not a local upload).
3. In the Render dashboard: **New +** → **Blueprint** → pick this repo.
   Render reads `render.yaml` and shows you the one service it defines.
4. When prompted for `API_KEY` (marked `sync: false` in the blueprint so
   it's never committed), paste your Gemini key. Click **Apply** /
   **Create**.
5. Render builds the Docker image and deploys — watch progress in the
   dashboard's **Logs** tab. First build takes a few minutes; free-plan
   services also spin down after 15 minutes idle and cold-start (a several
   -second delay) on the next request after that.
6. Once live, Render shows your URL as `https://<service-name>.onrender.com`
   — open `<that-url>/chat`.

No CLI needed for this one — the whole flow is the Render dashboard once
you've pushed to GitHub. To redeploy after a code change, just push to the
connected branch; Render auto-deploys from it by default.

## 4. Fly.io (free, payment method required for verification)

`fly.toml` in the repo already has everything wired up — a persistent
volume mounted at `/data`, `DATABASE_URL`/`SQLITE_DATA_DIR` pointed at it,
and a single-instance config (`min_machines_running = 0`, one VM defined —
it scales to zero when idle and back to exactly one on the next request,
never more than one at a time). You still need your own account.

1. **Sign up** at <https://fly.io>. Fly.io requires a payment method on
   file even for the free allowance (an anti-abuse measure on their end) —
   it won't be charged as long as you stay within it, but know that going
   in.
2. **Install `flyctl`** (Windows, PowerShell):
   ```powershell
   iwr https://fly.io/install.ps1 -useb | iex
   ```
   Then open a new terminal so it's on your `PATH`.
3. **Log in:**
   ```bash
   fly auth login
   ```
   (Opens your browser to complete login — nothing to paste back here.)
4. **Pick an app name.** Edit `app = "smart-accounting-rima"` in
   `fly.toml` to something globally unique to you (Fly checks this when
   you create the app). Optionally also change `primary_region` — run
   `fly platform regions` to see the list.
5. **Create the app and its volume** (region must match `primary_region`
   in `fly.toml`):
   ```bash
   fly apps create <your-app-name>
   fly volumes create accounting_data --size 1 --region <region>
   ```
6. **Set your Gemini key as a secret** (never put this in `fly.toml` —
   that file is meant to be committed):
   ```bash
   fly secrets set API_KEY=your-gemini-api-key
   ```
7. **Deploy:**
   ```bash
   fly deploy
   ```
8. **Check it worked:**
   ```bash
   fly status
   fly logs
   ```
   Look for the "Seeded /data/accounting.db..." line on the first deploy.
   Then open `https://<your-app-name>.fly.dev/chat`.

To redeploy after a code change, just `fly deploy` again — `/data` (and
your chart of accounts on it) isn't touched by a redeploy, only by
deleting the volume.

## 5. Alternative: AWS App Runner

Simplest option for a single container with a public HTTPS URL — no VPC,
load balancer, or EC2 instance to manage yourself.

1. **Install & configure the AWS CLI** with credentials that have ECR and
   App Runner permissions:
   ```bash
   aws configure
   ```

2. **Create an ECR repository and push the image:**
   ```bash
   aws ecr create-repository --repository-name smart-accounting-rima --region <region>

   aws ecr get-login-password --region <region> \
     | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com

   docker tag smart-accounting-rima:latest \
     <account-id>.dkr.ecr.<region>.amazonaws.com/smart-accounting-rima:latest

   docker push <account-id>.dkr.ecr.<region>.amazonaws.com/smart-accounting-rima:latest
   ```

3. **Create the App Runner service** (console is easiest for a first pass:
   App Runner → Create service → Container registry → pick the ECR image).
   Either way, set:
   - **Port**: `8000`
   - **Environment variables**: `API_KEY` = your Gemini key (as a secret,
     not plaintext, if you want it out of the console history)
   - **Auto scaling → Min size = Max size = 1.** This is not optional given
     section 1 above — more than one instance means users randomly land on
     different SQLite files and different conversation memories.

4. App Runner gives you a public HTTPS URL once deployed — open
   `<that-url>/chat`.

## 6. Alternative: a single EC2 instance

Worth it specifically if you want the SQLite data to survive container
restarts (App Runner's filesystem is ephemeral; a bind-mounted file on a
real VM is not).

1. Launch a small instance (`t3.micro`/`t3.small`), Amazon Linux 2023, with
   Docker installed (via user-data or `sudo yum install -y docker` after
   launch).
2. Open port 8000 in the instance's security group (or put a reverse proxy
   in front for real HTTPS — out of scope here).
3. Get the code onto the instance (`git clone`/`scp`), then:
   ```bash
   docker build -t smart-accounting-rima .
   docker run -d -p 8000:8000 \
     -e API_KEY=your-gemini-api-key \
     -v /home/ec2-user/accounting.db:/app/accounting.db \
     smart-accounting-rima
   ```
   The `-v` bind mount is what makes the DB file persist across container
   restarts — without it you're back to section 1's caveat.
4. Prefer not to put the API key on the command line long-term? Use an EC2
   instance profile + Secrets Manager/SSM Parameter Store instead, and pull
   it into the environment via the instance's startup script.

## 7. What's in the repo for this

| File | Purpose |
| --- | --- |
| `Dockerfile` | Python 3.11-slim, installs `requirements.txt`, runs `entrypoint.sh` on port 8000. |
| `entrypoint.sh` | Seeds `SQLITE_DATA_DIR` from the image's `accounting.db` on first boot if that path is empty, then execs uvicorn. No-op (just runs uvicorn) if `SQLITE_DATA_DIR` isn't set. |
| `.gitattributes` | Forces LF line endings on `*.sh` — a CRLF shebang line breaks `entrypoint.sh` inside the Linux container if this repo is checked out on Windows without it. |
| `.dockerignore` | Keeps `.venv`, `.git`, `.env`, `tests/` out of the image. `accounting.db` is intentionally *not* excluded — it's the seed data, see section 2. |
| `fly.toml` | Fly.io app config: the persistent volume mount, `DATABASE_URL`/`SQLITE_DATA_DIR`, and the single-instance settings. Edit the `app` name before your first deploy. |
| `render.yaml` | Render Blueprint: Docker build, free plan, health check path, `API_KEY` marked as a secret you fill in during setup. |
| `static/chat.html` | The Rima testing chat UI, served at `GET /chat`. |
