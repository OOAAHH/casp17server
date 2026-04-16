# Query Mailer Deployment Pack

This repository is a sanitized deployment reference for `query-mailer`.

It is intended for publication and reuse, so all environment-specific values have been replaced with placeholders:

- no real domains
- no real webhook URLs
- no real user emails
- no real server paths
- no real internal ports
- no request log samples from the live environment

## Overview

`query-mailer` accepts external submission requests, stores every request as JSON, and sends Feishu notifications through two channels:

- `FEISHU_WEBHOOK`: accepted-request summary for humans
- `FEISHU_REJECTED_WEBHOOK`: raw request log for all requests

The second variable keeps its historical name for compatibility, but in the current design it acts as the raw/log channel, not just the rejection channel.

## Current Behavior

- Accepts `GET` and `POST` on `/` and `/submit`
- Supports query-string submissions and `application/x-www-form-urlencoded` `POST`
- Stores every request before validation or delivery
- Validates normalized `sequence`
- Sends an accepted summary to the summary webhook
- Sends the raw request payload to the raw/log webhook
- Retries failed or pending notification channels from a replay timer or CLI

## Request Compatibility

The service currently accepts:

- `sequence` / `SEQUENCE`
- `target` / `TARGET`
- `reply_email` / `REPLY_EMAIL`
- `email` / `EMAIL`
- `gzlab` / `GZLAB`
- `token` / `TOKEN`
- `stoichiometry` / `STOICHIOMETRY`

It also tolerates:

- malformed fragments such as `targetTargetName`
- FASTA-style input with real newlines
- FASTA-style input with literal escaped `\n`
- FASTA-style input with literal escaped `\r\n`

## Responses

- `GET` success: `200 text/plain`, first line remains `OK`
- `GET` failure: `400 text/plain` with a human-readable reason
- `POST` success: `200 application/json`
- `POST` failure: `400 application/json`

Example successful `GET` response:

```text
OK
Request accepted.
Received at (UTC): 2026-01-01T00:00:00Z
Target: ExampleTarget
Sequence length: 13
If there are any questions, contact: support@example.org
```

Example successful `POST` response:

```json
{
  "ok": true,
  "request_status": "accepted",
  "message": "Request accepted.",
  "reason": "",
  "received_at_utc": "2026-01-01T00:00:00Z",
  "target": "ExampleTarget",
  "reply_email": "submitter@example.org",
  "sequence_length": 13,
  "contact_email": "support@example.org"
}
```

## Repository Layout

- `query_mailer/`: FastAPI app, parsing, storage, delivery, replay
- `deploy/`: sanitized nginx, systemd, and landing-page examples
- `CURRENT_SETUP_zh.md`: current genericized architecture and behavior
- `DEPLOY_ANOTHER_SERVER_zh.md`: generic deployment steps
- `PROBLEMS_AND_FIXES_zh.md`: deployment issues and the chosen fixes

## Environment Template

See [.env.example](./.env.example).

## Local Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
uvicorn query_mailer.app:app --host localhost --port __DEV_PORT__
```

`__DEV_PORT__` above is a placeholder. In production, keep the application on a loopback-only internal bind address and expose it through a reverse proxy.

## Quick Smoke Tests

Accepted `GET`:

```bash
curl "http://localhost:__DEV_PORT__/?sequence=AFCDELMKDTKTW&email=submitter@example.org&target=ExampleTarget"
```

Accepted `POST`:

```bash
curl -X POST "http://localhost:__DEV_PORT__/" \
  -d "sequence=AFCDELMKDTKTW" \
  -d "target=ExampleTarget" \
  -d "email=submitter@example.org"
```

FASTA with real newlines:

```bash
curl --get "http://localhost:__DEV_PORT__/" \
  --data-urlencode $'sequence=>ExampleTarget|\nGCCCGGAUAGCUCAGUCGGUAGAGCAGCGGGCACUAUGGGCGCAGUGUCAAUGGACGCUGACGGUACAGGCCAGACAAUUAUUGUCUGGUAUAGUGCCCGCGGGUCCAGGGUUCAAGUCCCUGUUCGGGCGCCA\n' \
  --data-urlencode "target=ExampleTarget" \
  --data-urlencode "email=submitter@example.org"
```

FASTA with literal escaped newlines:

```bash
curl -X POST "http://localhost:__DEV_PORT__/" \
  --data-raw 'sequence=%3EExampleTarget|\nGCCCGGAUAGCUCAGUCGGUAGAGCAGCGGGCACUAUGGGCGCAGUGUCAAUGGACGCUGACGGUACAGGCCAGACAAUUAUUGUCUGGUAUAGUGCCCGCGGGUCCAGGGUUCAAGUCCCUGUUCGGGCGCCA\n&target=ExampleTarget&email=submitter@example.org'
```
