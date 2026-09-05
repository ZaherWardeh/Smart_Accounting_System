# Deploying to AWS

This covers containerizing the app and putting it on AWS for **testing/demo
purposes**. It stops short of actually deploying — these are the files and
the steps, for you to run once you're ready.

## 1. Read this first: constraints of the current design

Two things about how the app is built right now matter a lot once it leaves
your laptop:

- **SQLite (`accounting.db`) is a single file inside the container.** It is
  not a shared database — if more than one container instance runs, each
  gets its own independent copy, and nothing is synced between them.
- **Conversation memory (`graph.py`'s `_CONVERSATIONS`) is an in-memory,
  process-local dict.** It lives only inside one running process. A second
  instance (or a restart of the same one) has no idea a given
  `conversation_id` ever existed.

Neither of these is a bug to fix before testing — they're documented,
known limitations (see `README.md`). But they mean: **run exactly one
instance, and expect both the DB and all conversation history to reset on
every redeploy/restart.** That's fine for demoing Rima to a client; it is
not a foundation for anything you need to keep. Moving past that would mean
an external DB (RDS/Postgres) and an external store for conversation state
(DynamoDB/Redis) — a real follow-up, not part of this.

## 2. Build & test the image locally first

```bash
docker build -t smart-accounting-rima .
docker run -p 8000:8000 -e API_KEY=your-gemini-api-key smart-accounting-rima
```

Open `http://localhost:8000/chat` and talk to Rima before touching AWS at
all — confirms the container itself is correct, independent of anything
AWS-specific.

Note: `accounting.db` as it exists in your working copy right now **is
baked into the image** (it's not excluded in `.dockerignore`), so the
container starts with your current chart of accounts/transactions already
in it — useful for a demo, but remember any changes made through the
running container are lost when the container is removed. Swap in a
different `accounting.db` before building if you want different seed data,
or exclude it and let `Base.metadata.create_all` start from empty.

`.env` **is** excluded from the image on purpose — the Gemini `API_KEY`
must never be baked into an image that might get pushed to a registry.
Always pass it as a runtime environment variable, as above.

## 3. Recommended: AWS App Runner

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

## 4. Alternative: a single EC2 instance

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

## 5. What's in the repo for this

| File | Purpose |
| --- | --- |
| `Dockerfile` | Python 3.11-slim, installs `requirements.txt`, runs `uvicorn main:app` on port 8000. |
| `.dockerignore` | Keeps `.venv`, `.git`, `.env`, `tests/` out of the image. `accounting.db` is intentionally *not* excluded — see section 2. |
| `static/chat.html` | The Rima testing chat UI, served at `GET /chat`. |
