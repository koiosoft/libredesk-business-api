---
name: libredesk-business-api-devops
description: Operate and maintain the Customer Hub production stack (LibreDesk + hub-api) on host 192.168.1.107. Use for every task involving => reviewing the Kanboard board, taking a Ready card, backing up PostgreSQL, deploying hub-api or LibreDesk, changing rules under rules/prod, diagnosing the JEV enforcement loop, or creating automation rules and webhooks through the API. Follow the commands and gates literally; each gate blocks.
---

# Customer Hub — DevOps operations

Host `192.168.1.107`. URL `https://customer-hub.koiosoft.com`. Docker network
`libredesk-network`, subnet `172.25.0.0/16`. Never assume the development range.

## 1. Gates — all of them block, no exceptions

- Take no action that recreates a container or lands changes on `stable` before completing §3. A gate failure means stop and report; never proceed "because it is only config".
- Always pass `-f compose.yaml -f compose.prod.yaml` plus both env files, and always name the service. Bare `up`, `down` or `restart` is forbidden.
- Push to `stable` only after reading explicit written approval in that card's comments.
- Never print or paste secrets, API keys, tokens or the SSH passphrase — not into commits, cards, logs or chat. The passphrase lives in `~/git-phrase.txt`; keys load from `~/.ssh/agent/pi.git.sock` via `IdentityAgent`. Read them programmatically.
- Run the secret scan on the staged diff before committing. Any hit stops the commit.
- Treat container logs as sensitive while `LOG_LEVEL=debug`: they contain customer message bodies.
- Post evidence in the card, never in chat.
- Verify current state with §2 before acting. Do not trust any value quoted in this file.

## 2. Measure current state first

```bash
cd ~/services/customers-hub/libredesk
docker ps --format '{{.Names}}\t{{.Status}}'
HK=$(grep '^HUB_API_KEY=' .env.production | cut -d= -f2)
curl -s http://127.0.0.1:8091/meta/config -H "X-Api-Key: $HK" | python3 -m json.tool
docker exec libredesk_db psql -U libredesk -d libredesk -tAc \
  "select id,name,enabled,left(rules::text,1) from automation_rules order by id;"
docker exec libredesk_db psql -U libredesk -d libredesk -tAc \
  "select id,name,url,is_active from webhooks;"
git -C ../libredesk-business-api rev-parse --short HEAD stable origin/stable
git -C . rev-parse --short HEAD stable origin/stable
```

Record what these return in the card before making changes.

### Service map

| Service | Container | Image | Source tree @ branch |
|---|---|---|---|
| LibreDesk core | `libredesk_app` | pinned digest `sha256:1c5a234b…` (v2.9.2) | `~/services/customers-hub/libredesk` @ `stable` |
| Business API | `koiosoft_api_hub` | `libredesk-api-hub` (local build) | `~/services/customers-hub/libredesk-business-api` @ `stable` |
| PostgreSQL | `libredesk_db` | `postgres:17-alpine` | volume `libredesk-postgres-data` |
| Redis | `libredesk_redis` | `redis:7-alpine` | own volume |
| Tunnel | `libredesk_cloudflared` | `cloudflare/cloudflared:latest` | exposes `app:9000` |

### Fixed constraints

- Keep the image digest pin in the production override. Removing it makes every boot pull upstream's current release. Changing the LibreDesk image requires an explicit decision recorded in a card.
- Deploy only from `~/services/customers-hub/*`. `repo-source/` is read-only reference: never deploy from it, never commit to it.
- Pass both `--env-file .env.build --env-file .env.production`. Omitting `.env.build` yields blank-variable warnings and a container that fails validation at boot.
- Restart `api-hub` only. Restarting `app`, `db`, `redis` or `cloudflared` requires separate authorization.
- Schedule any authorized `app` restart immediately after an automation time-trigger tick: the ticker is hardcoded to 1 hour (`internal/automation/automation.go:139`) and its phase resets at process start, so each restart costs up to one hour of sweeps.
- Configure time triggers in UTC. Local-hour intent must be converted.
- Pin any newly added service by digest, like `app`.
- There are no internal pre-send hooks in LibreDesk. Implement outbound message control externally through the webhook → classify → append path. Do not plan work assuming filter hooks exist.

### Enforcement path being maintained

```
contact writes (LiveChat / WhatsApp / email)
  → LibreDesk generates the assistant turn
  → webhook id=1 (6 events) → POST http://api-hub:8091/hooks/libredesk
  → hub-api classifies the turn with JEV
  → on deviation: generate via copilot, publish an ADDITIONAL labelled message
  → if the option declares post_action revive-assistant: reassign by team
  → automation rule id=11 assigns the bot back
```

Corrections are additive. Nothing is deleted and nothing is reassigned unless a rule opted in.

## 3. Backup — mandatory before §4(b), §4(c) and any `stable` rollout

```bash
TS=$(date +%Y%m%dT%H%M%SZ)
mkdir -p ~/services/customers-hub/"backup mandatory"
docker exec libredesk_db pg_dump -U libredesk -d libredesk -Fc -f /tmp/pre-<card>-$TS.dump
docker cp libredesk_db:/tmp/pre-<card>-$TS.dump \
  ~/services/customers-hub/"backup mandatory"/pre-<card>-$TS.dump
```

Use `docker exec`. Never use `docker compose exec` for dumps: password values in
`.env.production` contain unescaped `$`, compose interpolates them, and the resulting dump
is corrupt.

Validate by content and abort on failure:

```bash
docker cp ~/services/customers-hub/"backup mandatory"/pre-<card>-$TS.dump libredesk_db:/tmp/v.dump
N=$(docker exec libredesk_db pg_restore --list /tmp/v.dump | grep -c '^[0-9]')
[ "$N" -gt 500 ] || { echo "ABORT: TOC entries=$N"; exit 1; }
docker exec libredesk_db rm -f /tmp/v.dump
echo "RESPALDO OK ($N)"
```

A valid dump lists more than 500 TOC entries (~629 currently). Contaminated dumps list none.
Run validation inside `libredesk_db`: `pg_restore` is not installed on the host.

Name dumps `pre-<card>-<UTC>.dump`. Store rotated copies in `backup/` and permanent ones in
`backup mandatory/`. Do not delete anything from `backup mandatory/`.

## 4. Operations

### (a) Board cycle

Project **"Customer HUB - Koiosoft" id=4**. Columns: Backlog=13, Ready=14, WIP=15, Done=16.
Users: pi-devops=2, pi-architect=4.

1. Query tasks in project 4.
2. Act only on cards in Ready. Move the chosen card to WIP first.
3. Read the card's full comment thread before asserting about its state or its preconditions.
4. Obtain written approval in the comments before converging shared work or pushing to `stable`.
5. Report results as a comment with measured output. Move to Done only when the DoD holds.

Restart board surveillance at the beginning of every session:

```
/schedule prompt every 5m :: [DEVOPS HEARTBEAT & ADVANCE DIRECTIVE]
1. Query Kanboard project 4. If a card is in WIP, verify progress or finish it if its DoD holds.
2. When the active card closes successfully, move it to Done with its report, then take the next
   Ready card and move it to WIP.
3. Execute commands autonomously except where §1 gates require approval.
4. On a blocking failure, document it as a comment on the card and stop advancing.
5. Keep the loop alive until the board is drained.
```

### (b) Deploy hub-api

Execute in order. Step 4 blocks step 5.

```bash
cd ~/services/customers-hub/libredesk
# 1 backup per §3
# 2 sync the sibling repo
git -C ../libredesk-business-api fetch origin
git -C ../libredesk-business-api checkout stable
git -C ../libredesk-business-api pull --ff-only
# 3 build without starting
docker compose --env-file .env.build --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml build api-hub
# 4 read the rules hash from inside the new image
docker run --rm --entrypoint python libredesk-api-hub:latest -c \
  "import sys; sys.path.insert(0,'/app')
from app.core.rules import load_rules
print(load_rules('rules/prod').rules_hash)"
# 5 start only if step 4 matches the expected hash
docker compose --env-file .env.build --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml up -d api-hub
```

Stop conditions:

| Check | Required | Action if different |
|---|---|---|
| step 4 hash | equals the hash recorded in the card | do not run step 5; the build did not take the commit |
| `/meta/config` → `rules.hash` | equals step 4 | running an older image; rebuild |
| `classifier.api_key_set` and `libredesk_api_credentials_set` | both `true` | env files missing or wrong pair passed |
| traceback count | `0` | go to §4(d) |
| other containers' uptime | unchanged | an unscoped command ran; report and stop |

### (c) Change production rules

`rules/prod/*.yaml` is versioned configuration reviewed like code.

1. Edit the YAML on `stable` in the hub-api repository.
2. Compute the new hash with the authoritative loader:
   ```bash
   .venv/bin/python -c "from app.core.rules import load_rules; \
   print(load_rules('rules/prod').rules_hash)"
   ```
   Reimplementing the digest by hand is forbidden: a manual formula differs from the loader and
   will reject a correct deployment.
3. Commit and push to `stable` after approval (§1).
4. Run §4(b).
5. Record old hash → new hash in the card. The hash pair is the only identifier of which rules
   were live at a moment.

Rules contract:

- A rule set is exactly three files: `prompts.yaml`, `agents.yaml`, `prompt-augmenter.md`. Missing or invalid → startup aborts. Do not soften this.
- Keys in `agents.yaml` are `ai_assistants.id`. Never the bot's `user_id`.
- `none` is mandatory in `options`.
- Options may use `{text, post_action}`; the only valid `post_action` is `revive-assistant`.
- `revive-assistant` requires `revive_team_id` and `bot_user_id` in `agents.yaml` **and** a matching automation rule. Verify the rule with §4(e); otherwise the reassignment succeeds and does nothing.
- Write observable conditions in option text ("asks two or more questions"), not intents ("did not engage properly"). Interpretive wording gets discarded at low confidence.
- Channel keys are `chat` and `email`. Raw `whatsapp` and `livechat` normalise to `chat`.
- Rules load once at boot: restart to apply.

### (d) Diagnose the loop

```bash
docker logs koiosoft_api_hub --since 30m | grep -E "entering pipeline|ignored reason|outcome=|jev decision"
docker logs koiosoft_api_hub --since 30m | grep -cE "AttributeError|Traceback"
curl -s http://127.0.0.1:8091/healthz
```

Expected traceback count is `0`. Anything else goes to §4(d)-escalation below.

These discard reasons are correct behaviour. Do not treat them as incidents and do not change
thresholds because of them: `not_outgoing`, `private_or_missing`, `no_ai_assistant_id`,
`author_not_ai_assistant`, `agent_not_allowlisted`, `jev_said_none`, `low_confidence`,
`correction_limit_reached`, `no_prefix_for_channel:<channel>`.

Route by symptom:

| Symptom | Cause | Action |
|---|---|---|
| no `entering pipeline` lines | event never arrived | check `HUB_ALLOWED_IPS` against the caller IP, the HMAC signature, and the webhook event list |
| `agent_not_allowlisted` | id absent from active `agents.yaml` | read `/meta/config` hash first, then fix the rule set |
| `jev_said_none` / `low_confidence` | thresholds or option wording | leave as-is; escalate only with a sample of real cases |
| `no_prefix_for_channel:whatsapp` | channel not normalised | an old image is running; redeploy |
| `generation_empty` | model exhausted its output budget reasoning | check OpenRouter for `finish_reason=length` with `completion_tokens` at the provider cap; raise `max_tokens` in Admin → AI Providers, or remove contradictory policy wording. Not a hub-api defect |
| `outcome=corrected` but invisible to the customer | delivery is asynchronous | publication returns `status=pending`; channel rejection arrives later via `message.updated` |
| tracebacks present | exception inside a background task | the webhook already answered 202, so events are being dropped silently. Stop, capture the traceback, open a card |

For payload inspection, use development only:

```bash
# set CLASSIFIER_LOG_REQUEST=true and/or COMPLETION_LOG_REQUEST=true, restart, then:
python scripts/grab-logs.py --since 30m
```

Turn both flags off afterwards. Never enable them casually in production.

### (e) API and database operations

Create automation rules by sending `rules` as a JSON **object**, never as a string. A
string-encoded value returns HTTP 200, stores an enabled row and evaluates to nothing.
Verify after every create:

```bash
docker exec libredesk_db psql -U libredesk -d libredesk -tAc \
  "select id, left(rules::text,1) from automation_rules order by id desc limit 3;"
```

Accept `[` or `{`. A leading `"` means double-encoded and the rule is dead: delete it and recreate
with the object form.

Activate webhooks explicitly — creation leaves them inactive:

```
PUT /api/v1/webhooks/{id}/toggle
```

Read-only queries:

```bash
docker exec libredesk_db psql -U libredesk -d libredesk -tAc \
  "select a.id,u.first_name,a.user_id,a.enabled,a.max_turns,a.fallback_team_id
   from ai_assistants a join users u on u.id=a.user_id;"
docker exec libredesk_db psql -U libredesk -d libredesk -tAc \
  "select c.uuid,c.status_id,c.assigned_user_id,c.assigned_team_id
   from conversations c order by c.updated_at desc limit 10;"
```

Never write business rows by hand when the API supports it. Direct UPDATEs skip webhooks,
automation and SLA bookkeeping and produce states the application cannot reach.

## 5. Reference documents

Read the matching document before changing what it governs. This skill does not override it.

| Path | Read when |
|---|---|
| `libredesk-business-api/.sdd/core/SPEC.md` | architecture, components, HTTP surface, data design |
| `libredesk-business-api/.sdd/core/CONVENTIONS.md` | writing or reviewing code, logging, error policy, rule-set contract, tests |
| `libredesk-business-api/.sdd/core/git/COMMITS.md` | composing any commit message |
| `libredesk-business-api/.sdd/core/git/RELEASE.md` | releasing, tagging, syncing `stable` |
| `libredesk-business-api/.agents/skills/current-project/SKILL.md` | building or maintaining hub-api itself |
| `libredesk-business-api/.sdd/inputs/FOLLOW_UP.md` | open items and accepted limitations |

## 6. Verification discipline

- Fetch before stating anything about a remote branch, tag or deployed version.
- Validate with the authoritative code path, never a reimplemented formula.
- Feed test fixtures verbatim captured responses; a double shaped by assumption proves nothing.
- Re-read the full comment thread before reporting that a precondition is unmet.
- Update this file in the same change that corrects a fact in it. Unmeasured statements must be labelled.
