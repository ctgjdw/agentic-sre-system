# Handoff: Agentic SRE Team - implementation sessions

## Prompt to start the next session with

> Continue executing the `/agentic-sre-team` implementation plan
> (`agentic-sre-team/docs/superpowers/plans/2026-07-11-agentic-sre-team-implementation.md`)
> with superpowers:subagent-driven-development. I am Opus, the orchestrator: I dispatch
> Sonnet implementer subagents and review their work inline myself; the only delegated
> review is the per-phase cold whole-branch review, which runs on a fresh Opus4.8 agent
> (user directive as of Phase 5 - Opus now, not Fable). Read the plan header (Global
> Constraints, Locked implementation decisions, Execution conventions), this handoff, and
> the durable progress ledger at `.superpowers/sdd/progress.md` before dispatching. NOTE
> the ledger lives at the REPO ROOT `.superpowers/sdd/progress.md` (i.e.
> `~/Code/agentic-ons/.superpowers/sdd/`), NOT under `agentic-sre-team/`. Resume at
> **Phase 7, Task 36** (Pipeline-failure cases: GitHub `workflow_run` + GitLab pipeline
> webhooks, one `ScmProvider` over GitHub+GitLab, the changes/ci workers' evidence path)
> on a fresh branch `feat/sre-team-p7-scm` (off `main` @ `222e674`; Phases 0-6 merged,
> gateway 119 tests green + `make smoke` PASS + `make e2e` PASS + UI 10 tests green). Phase
> 7 is Python gateway work (webhooks/pollers/providers) plus a holmes.yaml MCP-server entry.
> It NEEDS creds: GitHub token (in `.env`), a GitLab token + webhook secret (`GITLAB_*` are
> BLANK in `.env` - confirm with me), and a `spectre-mirror` repo. KEY constraint established
> in Phase 4: GitHub/GitLab have NO native Holmes 0.36.0 toolset (they are a *source*, not
> evidence), so the changes/ci workers need a GitHub/GitLab **MCP server** wired into
> holmes.yaml `mcp_servers:` (like the grafana MCP) - there is a `TODO(Phase 7)` marker in
> holmes.yaml. Do a docs-check (Context7 + a live probe) on the GitHub/GitLab webhook shapes,
> signature verification, and whichever MCP server you wire, BEFORE writing against them.
> Check in with me at the phase boundary before starting, and run autonomously within the
> phase. Do not re-litigate approved decisions and do not re-review the plan.
>
> Two recurring operational notes: (1) subagents have hit a shared session limit and the
> cold-review agent has died mid-run on BOTH Phase 5 and Phase 6 (~20-35 tool calls in, API
> connection closed) - when that happens, recover the review INLINE from the agent transcript
> (`~/.claude/projects/-Users-alexgoh-Code-agentic-ons/<session>/subagents/agent-<id>.jsonl`;
> mine thinking + tool calls for findings, then verify each yourself). Consider a shorter or
> chunked cold-review prompt. (2) This is a background session; use `$CLAUDE_JOB_DIR/tmp` for
> scratch, and macOS has no `timeout` command (use the Bash tool's own `timeout` param).

## State (2026-07-15, end of Phase 6)

- **Phases 0-6 are COMPLETE and merged to `main`** (`main` @ `222e674`; local fast-forward
  merges, NOT pushed to origin - user chose local-only integration; main is 59 commits
  ahead of origin/main). Each phase was per-task reviewed inline by the Opus controller,
  then cold-reviewed as a whole branch at the phase boundary (Phases 1-4 on a **Fable**
  agent; **Phases 5-6 on Opus 4.8 per a user directive** - use Opus for cold reviews now),
  findings triaged + fixed, then `git merge --ff-only`.
- **Phase 6 (Telegram companion) delivered** (5 commits `a0b362a..222e674`): `TelegramChannel`
  (long-poll `getUpdates`, inline-keyboard gate approvals authz'd on `telegram_allowed_user_ids`,
  **DM-only** report intake), `LlmScorer` (small-tier, falls back to `HeuristicScorer` - closed
  the standing HeuristicScorer-untested watch-item), app-lifespan wiring, `handle_report`, and
  two fix bundles. Gateway **119 tests pristine + ruff clean + `make smoke` PASS**. Live-verified
  against the real `@agent_sre_bot`: both gate approvals recorded (`@alex_gct`, `channel=telegram`
  -> case closed), DM report intake, and a user-friendly parked-error message.
- Phase 6 things worth remembering: (1) **DM-only report intake** (user directive) - a private-chat
  message to the bot is a report; group messages are notification/approval only. This sidesteps Bot
  API **privacy mode** entirely (a privacy-mode bot never sees free-form group chatter, but DMs are
  always delivered; `@agent_sre_bot` has `can_read_all_group_messages:false`). Spec + wireframe + plan
  were updated. (2) **`SRE_TELEGRAM_ENABLED` flag** (default false) gates activation, NOT token
  presence: the gateway container loads the real `.env` via `env_file`, so keying off the token alone
  auto-activated a live long-poll under `--profile fake` and broke `make smoke`/`make e2e` determinism.
  `make smoke`/`e2e` force it false; `make up` inherits from `.env`; the compose gateway `environment:`
  block interpolates `${SRE_TELEGRAM_ENABLED:-false}` so it wins over `env_file`. (3) The gate node
  (`gates.py`) already posts the decision echo, so `on_decision` returns ONLY the callback toast (no
  double-post). (4) Cold review found a real **bot-token leak**: httpx errors embed the token in the
  request URL, which reached `health["telegram"]` (unauthenticated `/api/healthz`) + logs - fixed with
  `TelegramChannel._redact`. (5) The fake profile drives ONE case per gateway lifetime (scripted model);
  a 2nd case hits "script exhausted" - a fake-profile limit, not a bug (but it exposed + we fixed the
  UUID/"node"-jargon leak in the parked-error channel message). LlmScorer end-to-end + a real multi-case
  run are DEFERRED to the Phase 9 live-profile acceptance demo (user decision).
- **Phase 5 (ops console UI) delivered** (9 commits `2864bec..65b2987`): Vite 7 / React 19
  / react-query 5 / react-router 7 ops console under `agentic-sre-team/ui/`. Task 27 scaffold
  (api client, SSE hook, theme tokens, nginx, Dockerfile), 28 case queue + activity timeline,
  29 case-detail shell + live progress ledger, 30 hypothesis board + evidence receipts, 31
  artifact review (citation inspector + outcome-preview approvals), 32 governance (budget bars,
  suppression counters, audit stream), 33 Playwright browser smoke. Then the Opus cold-review
  fix bundle (`a9bb00b`, `65b2987` - see below). **UI 10 vitest tests + `tsc --noEmit` clean +
  0 npm-audit vulns + `make e2e` PASS (real chromium) + gateway still 103 pristine + `make
  smoke` PASS.**
- Phase 5 things worth remembering: built the API types against the REAL gateway serializers
  (`gateway/src/sre_gateway/api/{cases,governance,activity,health}.py`), not the plan's
  snippets, which had drifted - Governance has NO `scm_draft_mr` yet (Phase 7, so it's
  optional in the UI type), Artifact is keyed by kind+version with NO `id`/`cost_usd` (only
  `model_id`), CaseSummary carries `tokens_in/out`+`tool_calls`. The `ui` compose service is
  behind its OWN `ui` profile so `make smoke` (`--profile fake`) stays gateway-only (the
  Phase-4 C1 lesson); `make up`/`up-fake` add `--profile ui`; `make e2e` does `down -v` first
  because the fake scripts drive exactly ONE case per gateway lifetime. Bumped vite@6->7 /
  vitest@2->3.2.7 / plugin-react@4->5 to clear the dev-toolchain esbuild/vite/mocker
  advisories (0 vulns). The Opus cold review found 4 real ledger/SSE defects the per-task
  pass missed (workers are UNGUARDED so emit no `node_start/end` - the ledger now
  reconstructs per-worker entries from the `tool_call` stream keyed by `event.worker`; the
  reconnect banner was gated on `status==="open"` to stop it flapping on idle cases; a
  listener named `error` was catching EventSource's native error event; the guarded `plan`
  node double-rendered). All fixed + live-verified.
- **Phase 4 (real integrations)** (6 commits `32d4910..891d5ab`, merged): HolmesGPT 0.36.0
  sidecar + live `/api/chat` contract (Task 23), Grafana Cloud alert poller (24), live Vertex
  Gemini providers + LangSmith passthrough (25), Grafana Explore deep links (26), + a cold-
  review fix bundle. Live-verified: `make holmes-check` (prometheus via the Grafana Cloud
  datasource proxy), `make live-check` (Gemini flash/pro + gemini-embedding-001 at dim 768),
  the Grafana alerts API, and the Explore deeplink format.
- Phase 4 surprises worth remembering (all live-verified, in the ledger): the real Holmes
  image is the **CLI** (run the server via `python server.py`; config at
  `/root/.holmes/config.yaml`; Vertex via `VERTEXAI_PROJECT`/`VERTEXAI_LOCATION` + ADC);
  holmes.yaml uses **`{{ env.VAR }}`** templating (quoted) and **block-style** mappings
  (its benedict loader rejects inline `{k: v}`); response_format needs the
  `{"type":"json_schema","json_schema":{...}}` envelope; the frontier tier **fell back to
  `gemini-2.5-pro`** because Claude is not enabled in the project's Vertex Model Garden
  (all anthropic ids 404 - a config-only swap once enabled); Gemini has **no
  `asia-southeast1`** access so `.env` `GOOGLE_CLOUD_LOCATION=global`; GitHub/GitLab have
  **no native Holmes toolset** in 0.36.0 (changes/ci workers need a GitHub/GitLab MCP
  server - `TODO(Phase 7)` in holmes.yaml); the Explore deeplink format is `?left=<json>`
  not `?panes=`.
- Compose profiles (as of Phase 5): `make up` = `--profile live --profile ui` (real holmes
  + ui); `make up-fake` = `--profile fake --profile ui` (fake-holmes + ui, dev target for
  the console at `http://localhost:8088`); `make smoke` = `--profile fake` ONLY (gateway +
  postgres + fake-holmes, NO ui/holmes); `make e2e` does `--profile ... down -v` then
  `--profile fake --profile ui up` and runs the Playwright smoke; `make down` covers all
  three profiles. `make test`/`make lint` now run both the gateway (uv/pytest/ruff) and the
  ui (`test-ui`/`lint-ui`, npm) suites.
- **Phase 7 NOT STARTED** on `feat/sre-team-p7-scm` (off `222e674`). Tasks 36-41, the
  pipeline-failure cases: GitHub `workflow_run` + GitLab pipeline webhooks (signature-verified),
  a poller against the Actions/Pipelines APIs, one `ScmProvider` over GitHub+GitLab, and the
  changes/ci workers' evidence path. Python gateway work + a holmes.yaml MCP-server entry.
  NEEDS creds: GitHub token (in `.env`), GitLab token + webhook secret (`GITLAB_*` BLANK - confirm
  with user), a `spectre-mirror` repo. KEY: GitHub/GitLab have NO native Holmes 0.36.0 toolset
  (established Phase 4) - the changes/ci workers need a GitHub/GitLab **MCP server** in holmes.yaml
  `mcp_servers:` (`TODO(Phase 7)` marker is already there). Docs-check the webhook shapes + sig
  verification + the MCP server before writing.
- Working tree at handoff: clean except the pre-existing unrelated
  `agentic-sre-framework/docs/llm-ops-spec/...` (never stage it) and this HANDOFF.md.

## Execution methodology (what has worked this build)

- **Roles:** Opus controller orchestrates. Implementers/fix agents are **Sonnet**
  subagents (`Agent` tool, `model: "sonnet"`). Per-task review is done **inline by the
  controller** (read the diff/files directly), NOT delegated. The one delegated review is
  the per-phase cold whole-branch review on a fresh agent - Phases 1-4 used **Fable**
  (`model: "fable"`; see the `sre-team-cold-reviews-fable` memory), but from **Phase 5 the
  user switched cold reviews to Opus 4.8** (`model: "opus"`) - use Opus now. NOTE
  (2026-07-15): subagents hit a shared **session limit** mid-Phase-4 (the Task 24
  implementer failed on it) and the Phase-5 Opus cold-review agent hit a mid-run **API
  error** (connection closed) at ~35 tool calls; when a subagent dies or stalls, the
  controller finishes the task / recovers the review inline (its transcript + thinking are
  in the task output dir; mine them for findings, then verify each yourself). Check
  availability before dispatching; be ready to implement inline.
- **Per-task loop:** `scripts/task-brief PLAN N` (SDD scripts live in the plugin cache:
  `.../superpowers/6.1.1/skills/subagent-driven-development/scripts/{task-brief,review-package}`)
  -> write a brief in `.superpowers/sdd/task-N-brief.md` augmenting the plan with any
  controller docs-check findings -> dispatch a Sonnet implementer with the brief path +
  scene-setting (interfaces from prior tasks, constraints, a report-file path) -> on DONE,
  **verify the claims yourself** (re-run `uv run pytest -q` + `ruff`, read the
  substantive/security files - do not trust the report) -> fix anything real (route back
  via SendMessage or fix inline) -> record in the ledger.
- **Per-phase loop (one phase = one branch off `main`):** finish all tasks, run the gate
  (`uv run pytest -q && uv run ruff check .`; also the ui suite if the phase touched it),
  then **ask the user** how to integrate (they consistently choose "cold whole-branch
  review, then fix + merge"; as of Phase 5 the reviewer is **Opus 4.8**, not Fable).
  Generate the package with `scripts/review-package <merge-base> <head>` (it writes a diff
  to `.superpowers/sdd/`), dispatch a fresh Opus reviewer over the branch (tell it to
  ignore `uv.lock`/`package-lock.json`), triage findings yourself, fix the Critical + all
  Important + the real Minors (the user fixes real issues before merge, not as fast-
  follows), verify (re-run the gate AND `make smoke` if compose/Makefile changed, `make
  e2e` if the UI changed), then `git checkout main && git merge --ff-only <branch>`. Check
  in at every phase boundary; run autonomously within a phase.
- **Durable state:** `.superpowers/sdd/progress.md` (at the REPO ROOT, not under
  `agentic-sre-team/`) is the recovery map (per-task status, commit SHAs, findings,
  deferred watch-items). Trust it + `git log` over memory after any compaction.
  Briefs/reports also live in `.superpowers/sdd/` (git-ignored scratch).
- **Cold reviews earn their keep:** every phase's cold review found real bugs the per-task
  pass missed - P1 duplicate-case race, P2 global fence-strip that would corrupt P3 runbook
  JSON, P3 Critical halt-routing bug, P4 a Critical compose-profile regression that broke
  `make smoke` + 3 security Importants (docker.sock, secret over-sharing, MCP write
  surface), and P5 the ledger dropping all per-worker structure (workers are unguarded ->
  no `node_start/end`) + a flapping reconnect banner on idle cases. Keep doing them.

## Immediate next work (Phase 7 / Tasks 36-41 - pipeline-failure cases)

- **Python gateway** (webhooks/pollers/providers) + a holmes.yaml change. Read the plan's
  Task 36-41 blocks and the spec's intake path #4 (GitHub `workflow_run` conclusion:failure +
  GitLab pipeline status:failed, signature-verified, plus a poller for envs where the SCM
  can't reach the gateway). The case kind is `pipeline_failure` (already in
  `domain/enums.py`); the graph's changes/ci workers already exist (built Phase 3) and route
  through the same triage->...->gate1->remediate->gate2->publish pipeline.
- **DOCS-CHECK FIRST** (load-bearing): GitHub + GitLab webhook payload shapes and signature
  verification (GitHub `X-Hub-Signature-256` HMAC-SHA256; GitLab `X-Gitlab-Token`), the
  Actions/Pipelines list APIs for the poller, and whichever **GitHub/GitLab MCP server** you
  wire into holmes.yaml (Context7 + a live probe against the real GitHub token in `.env`).
  Remember from Phase 4: Holmes 0.36.0 has NO native github/gitlab toolset - evidence for the
  changes/ci workers MUST come via an `mcp_servers:` entry (the grafana MCP is the pattern to
  copy; there's a `TODO(Phase 7)` marker in holmes.yaml).
- Creds: `SRE_GITHUB_TOKEN` is set in `.env`; `SRE_GITLAB_TOKEN`/`SRE_GITLAB_WEBHOOK_SECRET`/
  `SRE_GITHUB_WEBHOOK_SECRET` are BLANK - confirm with the user which SCMs to wire live and
  whether a `spectre-mirror` repo exists. `scm_draft_mr` is OFF by default and must NEVER be an
  agent tool (locked decision) - it stays a reviewed, human-triggered publish step only.
- Existing seams (all real + merged): `settings.py` already has `github_token`,
  `github_webhook_secret`, `gitlab_token`, `gitlab_webhook_secret`, `gitlab_base_url`,
  `scm_poll_enabled`, `scm_poll_interval_s`, `scm_draft_mr`. `intake/service.py IntakeService.
  ingest` + `domain/signal.py Signal`/`fingerprint_of` are the intake entry (mirror the grafana
  webhook + poller: `api/webhooks.py`, `intake/poller_grafana.py`, `intake/grafana.py`). The UI
  `Governance` type already carries an optional `scm_draft_mr` slot (Phase 5 left it optional
  for exactly this). Follow the grafana webhook's HMAC pattern (`intake/grafana.py
  verify_grafana_hmac`, constant-time `compare_digest`) - watch-item #9 (HMAC header token-order)
  was flagged for a Task-48 docs-check but the GitHub/GitLab sig schemes are their own thing.

## How to execute (mechanics)

- All gateway commands from `agentic-sre-team/gateway/` via `uv run ...`. `uv` 0.11.x +
  Docker installed and running. Env is macOS: **no `timeout` command** - use the Bash
  tool's own `timeout` param (ms) to guard a hanging run. If a Sonnet agent stalls AFTER
  committing (harness fluke seen 2-3x), verify the committed work directly - it is usually
  fine.
- `git diff <a>..<b> -- <paths>` with pathspec exclusions has misbehaved here (returns
  empty); read changed files directly or use `git show`.
- Python test fixtures accrete in `gateway/tests/conftest.py` (never copied per file); DB
  tests use testcontainers (pgvector; local Docker required). The full suite can be slow
  under container load - a run that hangs at 0% CPU is host contention, not the code;
  re-run clean.
- Docs-checks are load-bearing and have repeatedly caught drift - keep doing them for any
  SDK/API/CLI before writing against it (Context7 + a live/import smoke test). Remaining
  ones flagged in the plan: **Grafana provisioning in Task 48**. Task 46 (Spectre chaos
  middleware) is a separate PR in `~/Code/spectre` (that repo's conventions), merge before
  the error-storm acceptance demo.
- `.env` is real and filled (Vertex `global`, Grafana Cloud `bronzeacorn842`, GitHub
  token, Telegram tokens); never commit it. For real deep links set
  `SRE_GRAFANA_PROM_DS_UID=grafanacloud-prom` + `SRE_GRAFANA_LOKI_DS_UID=grafanacloud-logs`.

## Environment prerequisites by phase

- Phases 0-3 and 5: DONE - the fake profile (scripted model + fake Holmes) covers
  everything; `make smoke` + `make e2e` prove it (no external creds).
- Phase 4: DONE (Grafana Cloud + SA token, Vertex Gemini, pinned Holmes image, LangSmith
  all wired and live-verified).
- Phase 6: DONE (Telegram bot + group + allowed user ids in `.env`; `SRE_TELEGRAM_ENABLED`
  gates activation; live-verified gate approvals + DM report intake against `@agent_sre_bot`).
  The LlmScorer-end-to-end + real-multi-case live-PROFILE run was deferred to Phase 9.
- Phase 7 (NEXT): GitHub token (in `.env`) + GitLab token + webhook secrets (`GITLAB_*`/
  `SRE_GITHUB_WEBHOOK_SECRET` BLANK - confirm with user) + a `spectre-mirror` repo;
  GitHub/GitLab evidence for the changes/ci workers needs a GitHub/GitLab **MCP server** in
  holmes.yaml (no native toolset in Holmes 0.36.0). Phase 9: Spectre up + real metrics in the
  Grafana stack for the full traced acceptance demo.

## Deferred watch-items (tracked, not blocking - revisit at the noted task/phase)

- **RESOLVED (Phase 6):** `HeuristicScorer` untested - now covered by `tests/test_scorer.py`
  alongside `LlmScorer` (happy path via the scripted model + fallback-on-exception).
- **Phase 5 carry (UI):** Two accepted-not-fixed cold-review minors in
  the SSE hook: a token frame's empty `id:` can reset `lastEventId` so a mid-stream drop
  right after a token replays from seq 0 and appends duplicate ledger entries (narrow;
  `MAX_EVENTS`+fold cap the damage; no dupe observed in the normal idle case); and
  `Ledger.fold`'s `byNode` keys only on node name, so a node running twice across rounds
  overwrites (cosmetic - last wins). No automated a11y/contrast test for the UI (visual
  pass only, both themes). These are all low harm; revisit if they bite.
- **Phase 4 carry:** `HolmesClient` has no `aclose()` - the gateway lifespan builds
  `HolmesClient(settings.holmes_url)` but never closes its httpx client on shutdown (leak
  for the real-Holmes profile); add `aclose()` + close in lifespan when convenient.
  LangSmith traced-run demo not yet shown (env-gated wiring is in place; needs a real
  incident E2E = Spectre + metrics, Phase 9). Grafana-MCP read-only-ness rests on the SA
  token being Viewer (verified 403 on writes) - enable a tool-filter/read-only mode if the
  MCP endpoint supports it. Deep-link minors: may embed a tool description as the query if
  a prom/loki call lacks `result.invocation` (low harm); range hardcoded `now-1h` (anchor
  to case time later).
- **Older, still open:** `config_dir` CWD-relative default (compose sets
  `SRE_CONFIG_DIR=/config`); HMAC header token-order assumption (confirm in Task 48 Grafana
  docs-check); provider-4xx/auth retry classification `TODO` in `json_call.py`; degraded-DB
  `/healthz` branch untested; an Important-5 gate crash-window `TODO(Phase 4)` in `gates.py`
  (phase/status reconciliation on crash-mid-node); a rare (~1/7) pre-existing async-teardown
  connection-leak warning + psycopg ResourceWarning (do a test-harness hardening pass
  together).

## Approved decisions (do not reopen)

The plan's Global Constraints section restates them. Headlines: LangGraph 1.x as a library
in FastAPI (no LangGraph Server), Spectre as the reference SUT (config-described - see
amendment), HolmesGPT pinned sidecar as the read-only evidence engine, `models.yaml` tiers
(Gemini Flash small/medium; frontier was Claude-on-Vertex, **currently gemini-2.5-pro** as
a config-only fallback until Model Garden Claude is enabled; air-gap via LiteLLM), LangSmith
env-gated, GitHub+GitLab behind one ScmProvider, `scm_draft_mr` off by default and never an
agent tool, the triage->plan->parallel-workers->synthesize->rca->verify->gate1->remediate->
gate2->publish graph with budgets between nodes, Telegram-only channel, default-deny
manifests (no write-capable tool in the registry), append-only audit.

2026-07-12 amendment (locked decisions 15-16): the system is generic -
`config/environment.yaml` describes the target environment and every SUT-aware prompt
renders from it, so Spectre is only the shipped example. The Holmes evidence layer uses the
Grafana MCP server, `grafana/tempo` (comparative fast/slow trace sampling), and
`elasticsearch/data` + `elasticsearch/cluster` in place of the notional `opensearch` key
(OpenSearch-compatible), with `openshift/*` flipped on - as a reviewed git change - for
OpenShift targets. (Phase 4 reality: in Holmes 0.36.0 the real toolset keys are
`prometheus/metrics`, `grafana/loki`, `grafana/tempo`, `elasticsearch/data|cluster`,
`docker/core`, `database/sql`; GitHub/GitLab are NOT toolsets and need an MCP server.)

## User's working preferences observed this project

- Research-first before decisions; cite sources; live-verify against real systems before
  committing to a shape (Phase 4's holmes contract, Vertex model availability, Grafana auth
  were all settled by live probes, not assumptions). Approval gates between phases;
  `AskUserQuestion` works well.
- Cold whole-branch phase reviews: Phases 1-4 ran on a **Fable-level agent** (saved as the
  `sre-team-cold-reviews-fable` memory), but **as of Phase 5 the user switched them to Opus
  4.8** (`model: "opus"`). Findings verified/triaged by the controller, not blindly applied.
- Quality over dev cost: prefer robustness/simplicity/maintainability; fix real issues now
  rather than deferring (the user fixed all Phase-2 and Phase-4 Important findings before
  merge). Pristine test output is a gate - warnings are findings.
- Conventional commits, scope `sre-team` for code / `agentic-sre-team` for docs, no agent
  co-author line, plain dashes (no em dash). Stage narrowly (`git add <task files>`); never
  stage `.env`, the user's uncommitted `.env.example` edits made by another process, or the
  pre-existing `agentic-sre-framework/docs/llm-ops-spec/...`.
