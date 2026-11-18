#!/usr/bin/env bash
# Acceptance: a disposable project with empty volumes completes the setup wizard and runs
# its first check. It never touches the running project or its volumes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT="fs-clean-test-$$"
OVERRIDE=".local/clean-start.compose.yml"
mkdir -p .local
cat > "$OVERRIDE" <<'YAML'
services:
  postgres:
    ports: !override ["127.0.0.1:15433:5432"]
  redis:
    ports: !override ["127.0.0.1:16380:6379"]
  backend:
    ports: !override ["127.0.0.1:18001:8000"]
  lightrag:
    ports: !override ["127.0.0.1:19622:9621"]
  caddy:
    ports: !override ["127.0.0.1:18444:443"]
YAML
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml -f "$OVERRIDE")
cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
if [[ "${KEEP:-0}" == "1" ]]; then echo "keeping project $PROJECT for inspection"; else trap cleanup EXIT; fi

echo "starting an empty project ($PROJECT)"
"${COMPOSE[@]}" up -d --no-build postgres redis backend worker lightrag caddy
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:18001/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:18001/healthz >/dev/null

cd "$ROOT"
PYTHONPATH=backend CLEAN_BASE_URL=http://127.0.0.1:18001 backend/.venv/bin/python - <<'PY'
import os
import time

import httpx
import pyotp
from app.core.config import get_settings

base = os.environ["CLEAN_BASE_URL"]
settings = get_settings()
client = httpx.Client(base_url=base, timeout=120.0)
stamp = str(int(time.time()))
email = f"acceptance-{stamp}@clean.test"
password = f"Clean-Accept-{stamp}!"

def expect(response: httpx.Response, label: str) -> dict:
    if response.status_code >= 400:
        raise SystemExit(f"{label} failed: HTTP {response.status_code} {response.text[:500]}")
    return response.json() if response.content else {}

status = expect(client.get("/api/setup/status"), "status")
if status.get("complete"):
    raise SystemExit("the clean project is unexpectedly already set up")

created = expect(
    client.post(
        "/api/setup/admin",
        json={
            "token": settings.setup_token.get_secret_value(),
            "email": email,
            "password": password,
            "display_name": "Acceptance Admin",
        },
    ),
    "admin",
)
secret = created["totp_secret"]
code = pyotp.TOTP(secret).now()
expect(client.post("/api/setup/admin/totp", json={"token": settings.setup_token.get_secret_value(), "code": code}), "totp")
login = expect(client.post("/api/auth/login", json={"email": email, "password": password, "totp_code": code}), "login")
headers = {"X-CSRF-Token": login["csrf_token"]}
expect(
    client.post(
        "/api/setup/organization",
        headers=headers,
        json={"name": "Clean Acceptance", "organization": "Acceptance", "overview_public": False, "monthly_budget_usd": 15},
    ),
    "organization",
)
expect(
    client.post(
        "/api/setup/provider",
        headers=headers,
        json={
            "name": "deepseek",
            "base_url": settings.provider_chat_base_url,
            "api_key": os.environ.get("CLEAN_DEEPSEEK_API_KEY") or settings.deepseek_api_key.get_secret_value(),
            "is_local": False,
            "use": "chat",
        },
    ),
    "chat provider",
)
expect(
    client.post(
        "/api/setup/provider",
        headers=headers,
        json={
            "name": "ollama-local",
            "base_url": settings.provider_embedding_base_url,
            "is_local": True,
            "use": "embedding",
        },
    ),
    "embedding provider",
)
expect(
    client.post(
        "/api/setup/models",
        headers=headers,
        json={
            "chat_model": settings.provider_chat_model,
            "embedding_model": settings.provider_embedding_model,
            "embedding_dim": settings.embedding_dim,
            "multilingual": True,
        },
    ),
    "models",
)
expect(client.post("/api/setup/moderation-test", headers=headers, json={}), "moderation")
expect(client.post("/api/setup/complete", headers=headers, json={}), "complete")
status = expect(client.get("/api/setup/status"), "status after complete")
if not status.get("complete"):
    raise SystemExit("setup did not report complete")

check = client.post(
    "/v1/factcheck",
    headers=headers,
    json={"input": {"type": "text", "text": "The Berlin Wall fell in 1989."}, "fast": True},
)
expect(check, "first check submission")
payload = check.json()
job_id = (payload.get("result") or {}).get("job_id")
if job_id is None:
    job_id = (payload.get("job") or {}).get("id")
if job_id is None:
    raise SystemExit("the first check returned no job id")
result = {}
for _ in range(120):
    poll = expect(client.get(f"/v1/factcheck/{job_id}"), "poll")
    nested = poll.get("result")
    if nested is not None:
        result = nested.get("result") or {}
        if result.get("overall_verdict"):
            break
    time.sleep(2)
else:
    raise SystemExit("the first check did not produce a verdict")
print(
    f"CLEAN START PASSED: setup complete, first check result={result.get('id')} "
    f"verdict={result.get('overall_verdict')}"
)
PY
