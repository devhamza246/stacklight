# Deploying the public demo (Cloudflare Tunnel)

> **These steps change the server's public exposure. The build did not perform them.** Nothing below has been
> run; check the host facts in section 1 yourself immediately before you act.

The app has **no authentication** by design. Everything that keeps a public instance safe is configuration:
simulated send, scheduled KB reset, per-IP rate limits, a daily spend cap. Do the steps in order and do not skip
the limits.

## 1. Pre-flight (read-only)

```bash
ss -ltn                                   # which ports are listening, and on which address
docker ps --format '{{.Names}}\t{{.Ports}}'
docker network ls
```

Look for: the host port you plan to use (`STACKLIGHT_PORT`, default 8780) must not already be listening; note which
Docker network your existing Cloudflare tunnel container (`<existing-cloudflared-container>`) is attached to
(`<its-docker-network>`) and whether it uses host networking. If it is on a bridge network it cannot reach the host's
`127.0.0.1`, which drives the choice in section 4.

Names: deploy from a clone with its own compose project name (for example `~/stacklight-demo`, `-p stacklight-demo` on
every command). The containers are then `stacklight-demo-app-1`, `-worker-1`, `-postgres-1`, `-redis-1`; check they do
not clash with existing container names. The development database (`make dev-db`) uses a different project
(`stacklight-dev`), so it never touches a deployment. Never point a public instance at a database the test suite uses:
the tests truncate tables.

Memory: the four containers measured about 1.0 GB in total after seeding and one warm query (app about 680 MiB,
worker about 235 MiB, Postgres about 92 MiB, Redis about 4 MiB; limits 1 g, 1 g, 768 m, 192 m). Check that the host has that much memory free.

## 2. Configure `.env`

```bash
git clone <repo-url> ~/stacklight-demo && cd ~/stacklight-demo
cp .env.example .env && chmod 600 .env      # .env is git-ignored; never commit it
```

Edit `.env`:

```ini
STACKLIGHT_PORT=8780            # host port; any free one
# STACKLIGHT_BIND stays unset = 127.0.0.1. Do NOT set 0.0.0.0: the app has no auth.
POSTGRES_PASSWORD=<a long random value>
LLM_MODEL=<a cheap, priced model, e.g. claude-haiku-4-5>
ANTHROPIC_API_KEY=<key>         # or OPENAI_API_KEY for an OpenAI model
DAILY_SPEND_CAP_USD=2           # the demo pauses itself at this daily total (UTC day)
RATE_LIMIT_PER_MIN=20           # per client IP, on chat / curate / draft / approval decisions
```

Use a key created for this demo only, with a spend limit set at the provider as a second backstop. The in-app cap
checks when a run starts, so a run begun just under the cap can overshoot slightly, and several concurrent runs can
start together. Defaults if you leave a value out: the compose file uses `$5` and `30/min`; the code default is
`$2` and `20/min`. Pick explicit values. Other operational settings (`MAX_STREAMS_PER_IP`, `MAX_PENDING_RUNS`,
`MAX_CONCURRENT_RUNS`, `RUN_TIMEOUT_S`, `UNKNOWN_COST_PER_RUN_USD`, `AUTO_SEED`) are documented in `.env.example`.

Also set, behind the tunnel: `TRUST_PROXY_HEADERS=true` (add it to `.env`; compose passes it to the app).

Why: per-IP limits key on the socket peer. Behind the tunnel the peer is always cloudflared, so without this
every visitor shares one bucket and the first heavy user locks everyone out. With it set, the app uses
`CF-Connecting-IP` (then the first `X-Forwarded-For` entry). **It must stay `false` anywhere the app is reachable
without Cloudflare in front**, because those headers are client-supplied and a visitor could spoof a new IP on every
request and dodge the limit.

Leave `DEMO_RESET_INTERVAL_H` at its default (6 hours): the KB returns to the shipped corpus and approvals, audit rows
and run records are cleared. Spend history is kept (a reset does not reset the cap).

## 3. Start and verify locally

```bash
docker compose -p stacklight-demo up -d --build --wait
curl -s http://127.0.0.1:8780/health            # {"status":"ok"}
curl -s http://127.0.0.1:8780/api/status        # documents, kb_ready, spend_today_usd, cap_usd, status
```

First start downloads the two small models and seeds 81 documents (about 1.5 minutes on the build machine; the UI shows
"Preparing the knowledge base..." until `kb_ready` is true). The first image build is slow (CPU torch); later code
changes reuse the dependency layer.

## 4. Add a hostname to the existing tunnel

Pick the hostname (for example `stacklight.<your-domain>`). Because `<existing-cloudflared-container>` runs on the
`<its-docker-network>` network, make the app reachable **from that network** and point the tunnel at the container, not at
`127.0.0.1`.

### 4a. Let the app join the tunnel's network (recommended)

Create `docker-compose.override.yml` in the deploy clone:

```yaml
services:
  app:
    networks:
      stacklight: {}
      <its-docker-network>:
        aliases: [stacklight-app]
networks:
  <its-docker-network>:
    external: true
```

Then `docker compose -p stacklight-demo up -d`. The service target is `http://stacklight-app:8000` (container port
8000, not the host port). The host port can stay bound to `127.0.0.1` for local checks. If you prefer not to touch
compose files: `docker network connect --alias stacklight-app <its-docker-network> stacklight-demo-app-1` (lost when the
container is re-created).

### 4b. Alternatives (only if 4a is not wanted)

- Run a separate `cloudflared` for this app with `--network host` (or as a host service); it can then use
  `http://127.0.0.1:8780`.
- Bind the published port to the LAN address (`STACKLIGHT_BIND=<LAN-IP>`) and use `http://<LAN-IP>:8780`.
  This exposes an unauthenticated app to the whole LAN; do it only if that is acceptable.

### 4c. Register the hostname

Which one applies depends on how `<existing-cloudflared-container>` was set up (check `docker inspect` / its compose file for a
`--token` or a mounted `config.yml`):

- **Dashboard-managed tunnel (token):** Cloudflare Zero Trust, Networks, Tunnels, select the tunnel, Public hostname,
  Add: hostname `stacklight.<your-domain>`, service type HTTP, URL `stacklight-app:8000` (or the 4b address). Cloudflare
  creates the DNS record. No restart needed.
- **config.yml-managed tunnel:** add a rule **before** the catch-all, then create the DNS record and reload:

  ```yaml
  ingress:
    - hostname: stacklight.<your-domain>
      service: http://stacklight-app:8000
    # ...existing rules...
    - service: http_status:404
  ```

  ```bash
  cloudflared tunnel route dns <tunnel-name-or-id> stacklight.<your-domain>
  docker restart <existing-cloudflared-container>      # this briefly interrupts every site on that tunnel
  ```

Prefer the dashboard route when possible: it does not restart the tunnel that already serves your other sites.

Optional hardening in Cloudflare (not required by the app): a WAF rate-limiting rule on `/api/chat`, `/api/curate`
and `/api/draft`, and "Always use HTTPS". Do not enable Cloudflare Access unless you want visitors to log in; the demo
is meant to be open.

## 5. Check it end to end

```bash
curl -sI https://stacklight.<your-domain>/health
curl -s  https://stacklight.<your-domain>/api/status
```

Open the URL in a private window, run the prefilled question, open a citation, run the audit, and approve one fix.
Then check the rate limit sees real client IPs. Limit hits are logged as `rate limited client <short hash>`
(raw IPs are never logged). Temporarily set `RATE_LIMIT_PER_MIN=3`, send four questions quickly from one network and
confirm the fourth gets the "busy" notice; then confirm a phone on mobile data is still served. If everyone is
limited together, `TRUST_PROXY_HEADERS` is not taking effect. Restore the real value afterwards.

## 6. Operate

| Need | Command |
|---|---|
| Logs | `docker compose -p stacklight-demo logs -f app worker` |
| Health and spend | `curl -s http://127.0.0.1:8780/api/status` (`status`, `spend_today_usd`, `cap_usd`, `kb_ready`, `pending_runs`) |
| Container state / memory | `docker compose -p stacklight-demo ps`, `docker stats --no-stream` |
| Manual reset of the demo KB | `docker compose -p stacklight-demo exec app python -m app.cli reset-demo` (see warning below) |

**Manual and Celery resets bypass the in-API gate.** While the API's scheduled reset runs, it refuses approval
decisions (HTTP 503 `resetting`) and waits for runs to drain. The CLI command above and a reset run from the Celery
worker execute in a different process and do NOT set that flag, so only run them when no runs or approvals are in
flight.

**When the cap trips:** `/api/status` returns `"status":"demo_paused"`, the UI shows the paused banner, and new runs get
HTTP 503 until the next UTC midnight (`resets_at`). Nothing needs doing. To resume sooner, raise `DAILY_SPEND_CAP_USD`
in `.env` and `docker compose -p stacklight-demo up -d` (recreates the app container; the KB and spend history stay).
Check the provider's dashboard before raising it.

**Single worker:** runs and their event streams live in the API process, so keep one app replica and one uvicorn worker
(the default). A restart drops in-flight runs; the UI shows them as failed.

## 7. Rollback and teardown

```bash
# Take the demo offline but keep data:
docker compose -p stacklight-demo stop
# Remove the public hostname: delete the Public hostname in the dashboard (or remove the ingress rule and the DNS
# record, then restart the tunnel). Do this first if you suspect abuse.
# Remove everything including the database and model cache:
docker compose -p stacklight-demo down -v
```

Revoke or rotate the provider key if it may have leaked. Nothing else on the host is touched by these commands
(`-p stacklight-demo` scopes them to this project).

## 8. Uptime caveat

The demo lives on a self-hosted machine: it is down when that machine, its network or the tunnel is down, and a
cold restart takes about a minute to be ready (longer on first start). If the link will sit in proposals for weeks,
consider a small VPS (2 vCPU / 2 to 4 GB RAM) running the same compose file behind the same kind of tunnel. The 1.0 GB
measured footprint fits comfortably.
