# AI Provider Strategy

Date: 2026-08-16 (decision updated 2026-10-25)

## Decision

GerarAI's brain is **OpenCode Go with `deepseek-v4.1-flash`**, covered by the
owner's already-contracted OpenCode Go subscription. It is not a new provider
and it is not billed per token: the cost is the existing subscription.

```text
https://opencode.ai/zen/go/v1/chat/completions
```

The owner approved this model explicitly. The rest of the providers stay
opt-in and OFF by default:

- Groq (`openai/gpt-oss-120b`): optional chat-only backup.
- Gemini AI Studio: optional backup after Groq; requires confirming the key's
  project has no billing.
- OpenRouter `:free`: optional last-resort chat backup; requires a key and a
  `:free` model.
- Free OpenCode models (`deepseek-v4.1-flash-free`, `space-bunny-free`) remain
  available as verified-free legacy/reserve, normally through the optional
  local bridge.

## Approved models and startup guard

`GO_SUBSCRIPTION_MODELS = {"deepseek-v4.1-flash"}` is the owner-approved
subscription model; `VERIFIED_FREE_MODELS` keeps the real free models. The
guards accept `deepseek-v4.1-flash` only when the Go subscription is confirmed
(`CHAT_GO_SUBSCRIPTION_ENABLED=true`), and never claim it is free.

In production, startup fails with a clear error if `OPENCODE_GO_MODEL` (or a
non-empty `OPENCODE_GO_FALLBACK_MODEL`) is neither a verified free model nor
the approved Go model. The only escape hatch is the explicit, audited
`OPENCODE_GO_ALLOW_UNVERIFIED_MODEL=true`; it is never a silent override.

`/health/ready` applies the same check without generating anything or calling
remote providers: disabled provider, missing key, invalid URL, or an
unapproved model returns 503. Only a local bridge URL is probed (`/health`,
short timeout); the official Go endpoint is never contacted by readiness.

## Configuration

```env
LLM_ENABLED=true
LLM_PROVIDER=opencode-go
OPENCODE_GO_API_KEY=replace_with_the_owner_subscription_key
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
OPENCODE_GO_MODEL=deepseek-v4.1-flash
OPENCODE_GO_FALLBACK_MODEL=
OPENCODE_GO_REASONING_EFFORT=high
OPENCODE_GO_CHAT_REASONING_EFFORT=high
CHAT_TOTAL_TIMEOUT_SECONDS=45
CHAT_GO_SUBSCRIPTION_ENABLED=true
CHAT_GO_SUBSCRIPTION_BASE_URL=https://opencode.ai/zen/go/v1
OPENCODE_GO_ALLOW_UNVERIFIED_MODEL=false
```

Single source of truth: `app/core/config.py` defines the defaults (Go endpoint,
`deepseek-v4.1-flash`, no implicit fallback, `high` reasoning, 45 s chat budget).
`docker-compose.prod.yml` and the env examples pass or document the same values
to backend and workers.

`OPENCODE_GO_REASONING_EFFORT` is sent as `reasoning_effort` only to the models
listed in `OPENCODE_GO_REASONING_EFFORT_MODELS` (default includes the Go model
and the free legacy models). An empty value disables the parameter.

Long calls (document/principle extraction, theses, KPIs) keep a 120 s
per-attempt timeout, one retry and a 250 s total cap (`LLM_TIMEOUT_SECONDS`,
`LLM_MAX_RETRIES`, `LLM_TOTAL_TIMEOUT_SECONDS`). The interactive chat has its
own 45 s budget (`CHAT_TOTAL_TIMEOUT_SECONDS`) and races the Go primary against
the optional backups. The background chain retries once in
`SequentialFallbackProvider`, not inside the primary.

## Optional local bridge (free/legacy only)

The bridge (`data-engine/bridge/opencode_bridge.py`, port 4098) is no longer
the production requirement. It remains an optional path for verified free
models or legacy deployments: set `OPENCODE_GO_BASE_URL` to the bridge URL,
`OPENCODE_GO_MODEL` to a verified free model (for example
`deepseek-v4.1-flash-free`) and disable the Go chat switch. It has no streaming, no tools (400 on `tools`),
translates `response_format json_schema` into a prompt instruction, and has no
own auth (internal network only). Its `/health` endpoint is what readiness
probes when the URL is local.

## Chat chain

`create_chat_llm_provider` uses the Go subscription primary by default (model
pinned to `deepseek-v4.1-flash`). A paid/unapproved primary or fallback is
rejected before any network call; the default configuration never returns
`chat_primary_not_verified_free`. Groq/Gemini/OpenRouter only join when their
flags and confirmations are explicit; otherwise they are not built.

If the resolved primary model fails after its own retries, the adapter can
retry once with `OPENCODE_GO_FALLBACK_MODEL`. Empty means no implicit fallback.

## Free cascade (optional provider)

`LLM_PROVIDER=cascade` builds `CascadeProvider`: Gemini AI Studio
(`gemini-3.8-flash`) -> OpenRouter `:free` -> OpenCode, using only members with
a key. Per-member timeouts (~20 s) sit under a 60 s total cap. Privacy: with
cascade, any prompt can reach the Gemini free tier (Google may use it to
improve its products); cost-guarded flows (LLM proposals, bottleneck, news
narrative) reject cascade outright. OpenRouter `:free` does not guarantee
strict `json_schema`.

## Task routing

All task routes default to `deepseek-v4.1-flash` (the owner-approved Go model):
extraction, classification/news materiality, chat, thesis updates, deep
research, red-team review, document synthesis and tool workflows. A
`OPENCODE_GO_MODEL` or task override can change the model, but production
enforces the approved-model guard above.

## Cost and reliability

OpenCode Go applies its subscription quotas and model limits; this is a fixed
subscription, not a per-token charge. Free models are EUR 0 but lower quality
and may be unavailable via direct API (403 `FreeTierError`); that is why they
now live behind the optional bridge/legacy path. GerarAI keeps request timeout,
retry, daily cap and monthly cap controls so expensive workflows stay bounded.
Provider failures surface as typed LLM errors and never create unsupported
financial facts.

The API key is a secret and must live only in local `.env` files or deployment
secret stores. It must never be committed, placed in `config.yaml`, or exposed
in client-side code.

See the official model/endpoint list at:

https://opencode.ai/docs/zen/
