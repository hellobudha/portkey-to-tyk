# Migrating from Portkey to Tyk AI Studio

A practical guide for platform teams moving LLM traffic, governance and observability off Portkey (now branded "Prisma AIRS AI Gateway" after the Palo Alto Networks acquisition) and onto **Tyk AI Studio v2.2.2 Enterprise Edition**, the latest stable release at the time of writing.

**Written:** 23 October 2026. Both products move quickly; every claim below carries a source tag:

| Tag | Meaning |
|---|---|
| `[docs]` | Confirmed on tyk.io or portkey.ai documentation on 23 October 2026 (links in Appendix A) |
| `[stack]` | Observed live on a workshop installation running **v2.2.2 Enterprise** on 23 October 2026 (Appendix C lists the checks), or earlier on 2.2.1 where the text says so |
| `[unconfirmed]` | Not found in official documentation. Test it on your own installation before relying on it |

---

## Contents

1. [Why teams are migrating now](#1-why-teams-are-migrating-now)
2. [The mental model: Portkey concepts and their Tyk equivalents](#2-the-mental-model)
3. [Which edition do you need?](#3-which-edition-do-you-need)
4. [Before you start: inventory your Portkey estate](#4-before-you-start-inventory-your-portkey-estate)
5. [Stand up Tyk AI Studio v2.2.2](#5-stand-up-tyk-ai-studio-v222)
6. [Migration, step by step](#6-migration-step-by-step)
   - 6.1 Provider credentials: Integrations and virtual keys become Secrets and LLM providers
   - 6.2 Model prices
   - 6.3 Consumers: workspaces and API keys become Teams, catalogs and Apps
   - 6.4 Gateway Configs: fallback, load balancing, conditional routing, retries and timeouts
   - 6.5 Caching
   - 6.6 Guardrails become filters
   - 6.7 Budgets and rate limits
   - 6.8 Prompt templates and partials
   - 6.9 Observability: logs, traces, metrics, metadata and feedback
   - 6.10 Governance: SSO, RBAC, audit, webhooks
   - 6.11 MCP and agent gateways
7. [Client code changes](#7-client-code-changes)
8. [Cutover plan](#8-cutover-plan)
9. [Gap register: what does not map](#9-gap-register)
10. [Post-migration verification checklist](#10-post-migration-verification-checklist)
- Appendix A: Sources
- Appendix B: Worked example, Larkspur Bank's Compass assistant

---

## 1. Why teams are migrating now

You do not need a reason to evaluate a gateway, but three recent events explain why this guide exists:

- **Portkey was acquired by Palo Alto Networks.** The acquisition closed on 29 May 2026; Portkey becomes the AI Gateway inside Prisma AIRS, Palo Alto's AI security platform. Every Portkey docs page now carries a "Portkey is now PRISMA AIRS AI Gateway" banner and the docs site maintains three parallel trees ("Latest", "Prisma AIRS" and "Virtual Keys (Deprecated)"). The announcement says nothing about plan continuity for existing customers or the roadmap of the open-source gateway. `[docs]`
- **Portkey's object model changed under you.** Virtual Keys were deprecated in favour of the Model Catalog (Integrations, AI Providers, `@provider-slug/model` strings) during 2025, and Portkey's production gateway was merged into the open-source repository in March 2026 (released as gateway 2.0.0). `[docs]`
- **Tyk AI Studio reached a stable 2.2 line.** Version 2.2.0 (29 September 2026) unified the gateway surface behind one OpenAI-compatible **Main Ingress**, added failover, guardrails, fine-grained RBAC, audit trail, webhooks and semantic routing; 2.2.1 (2 October) and 2.2.2 (12 October, a microgateway security fix) hardened it. The source repository is licensed under AGPL-3.0, there are two editions (Community, free; Enterprise, licensed), and the documentation lists self-managed as the only deployment type: no hosted offering is documented. `[docs]`

What you gain beyond like-for-like: data classification enforced by the gateway (**privacy levels**), a self-service **AI Portal** with an approval flow for every credential, OpenAPI-defined **tools** served over REST and MCP, **data sources** for retrieval, a built-in **chat** for non-developers, and an **edge gateway** that keeps serving if the control plane is down. `[docs]`

What you give up: Portkey's prompt library, per-request metadata and feedback APIs, token-denominated budgets, same-target retries and the circuit breaker, and its very wide endpoint coverage (Responses, Realtime, Batches, Files). Section 9 lists every gap with a workaround where one exists.

---

## 2. The mental model

Portkey puts almost everything into one JSON **Config** attached to an API key or request. Tyk AI Studio spreads the same decisions across typed, governed objects, each with its own owner, audit history and catalog visibility. The migration is mostly an exercise in splitting Configs apart.

| Portkey concept | Tyk AI Studio equivalent | Notes |
|---|---|---|
| Organisation | One AI Studio installation (hub) | Multi-tenancy inside one hub is by **Teams**, **catalogs** and edge **namespaces** `[docs]` |
| Workspace | **Team** (API resource `groups`) plus the catalogs assigned to it | A user's Portal and Chat show the union of their Teams' catalogs `[docs]` `[stack]` |
| Integration (org-level credential store) | **Secret** (`Settings > Secrets`, referenced as `$SECRET/NAME`) | AES-256-GCM, keyed by `TYK_AI_SECRET_KEY`; the secrets list shows only whether a value is set and which objects use it `[docs]` |
| AI Provider / virtual key (`@slug`) | **LLM provider** (`LLM management > LLM providers`), slug derived from the name | Carries vendor, endpoint, `$SECRET` key, default model, **allowed models** (regex), **privacy level**, monthly budget, failover list, filters, plugins `[docs]` |
| `@provider-slug/model` | `{llm-slug}/{model}` on the Main Ingress | Same idea, different separator and no `@` `[docs]` `[stack]` |
| Workspace API key / service key | **App** credential (Key ID + Secret), issued through the AI Portal and **activated by an administrator** | One App per calling service. Grants (which providers, tools, data sources, routers) are checked on every request `[docs]` `[stack]` |
| Admin API key | **User API key** of an administrator (`Authorization: Bearer`) | Keys inherit the user's RBAC permissions `[docs]` |
| Config `strategy.mode: fallback` | **Failover** list on the LLM provider (up to 10 fallbacks) | Both editions `[docs]` `[stack]` |
| Config `strategy.mode: loadbalance` + `weight` | **Model Router** pool with the `weighted` algorithm | Enterprise, edge gateways only `[docs]` `[stack]` |
| Config `strategy.mode: conditional` | **Semantic Router** (routes by prompt content) or separate model strings per App | No routing on request metadata; see 6.4 `[docs]` |
| Config `retry` | Failover **triggers** (status codes, timeout, connection error) | Tyk does not retry the *same* target `[docs]` |
| Config `request_timeout` | Failover **per-attempt timeout** | `[docs]` |
| Config `cb_config` (circuit breaker) | None documented | Gap |
| Config `cache.mode: simple` | **LLM Response Cache** plugin (Community marketplace) | Exact match `[docs]` `[stack]` |
| Config `cache.mode: semantic` | **Advanced LLM Cache** plugin (Enterprise) | Exact match first, then cosine similarity `[docs]` `[stack]` |
| `input_guardrails` / `output_guardrails` | **Filters**: script (Tengo) or guardrail (no-code), attached to a provider, chat or tool | Executed only in Enterprise `[docs]` `[stack]` |
| Guardrail `deny: true` | Filter action **Block** | `[docs]` |
| Guardrail `deny: false` (log, status 246) | Filter action **Log**, or **Redact** | Portkey has no redact; Tyk has no "serve anyway but mark" status code `[docs]` |
| Usage-limit policy (cost or tokens, weekly or monthly) | **Budget** (currency, monthly) on App, LLM provider, Team or organisation | No token budgets, no weekly reset `[docs]` |
| Rate limit (RPM / TPM) on a provider or key | Community **LLM rate limiting** plugin, or a Tyk API Gateway in front | Not in the AI Studio core `[docs]` |
| Prompt template, partial, label, `/prompts/{id}/render` | No runtime prompt API | Chat experiences have per-room prompt templates; the Enterprise **Asset Catalog** plugin records prompts as governed assets but does not serve them `[docs]` |
| `x-portkey-metadata`, `_user` | No per-request metadata | Attribution is by App (and by user for chat); 2.2.1 logs `on_behalf_of` and `acting_agent` for delegated calls through auth plugins `[docs]` |
| `x-portkey-trace-id`, span headers | W3C `traceparent` propagated to the vendor; OTLP gRPC export of one span per LLM call | `[docs]` |
| Logs, Analytics | **Proxy logs** per App and provider (bodies optional), **Analytics** dashboards and `/api/v1/analytics/*` | `[docs]` `[stack]` |
| Feedback API | None documented | Gap |
| Log export (Enterprise, 50,000 rows per job) | Audit and compliance CSV/JSON exports; analytics API; proxy logs in the database | No bulk proxy-log export endpoint is documented `[docs]` |
| Audit logs | **Audit trail** (Enterprise): user, IP, action, resource, field-level diff, JSON lines on disk | `[docs]` `[stack]` |
| SSO (OIDC, SAML), SCIM | **Identity providers** (OIDC, SAML, LDAP via the embedded Tyk Identity Broker), IdP groups mapped to Teams | No SCIM documented `[docs]` `[stack]` |
| Webhook guardrail (bring your own) | Guardrail provider **HTTP classifier**, or `tyk.makeHTTPRequest` in a script filter | `[docs]` |
| MCP Gateway (`mcp.portkey.ai/{server-slug}/mcp`) | Every OpenAPI tool is served as MCP at `/tools/{slug}/mcp`; remote MCP servers go through **Tyk MCP Gateway** (Tyk Gateway 5.13+ for pass-through proxies, 5.15+ to convert REST APIs to MCP) and are imported into AI Studio (Enterprise) | `[docs]` `[stack]` |
| Agent Gateway (A2A) | No equivalent | Gap |

Two Tyk concepts have no Portkey ancestor and you must decide on them early:

- **Privacy levels.** Every provider, tool and data source carries a score from 0 to 100 (Public 0–25, Internal 26–50, Confidential 51–75, Restricted 76–100). A tool or data source can only be granted to an App whose providers have an equal or higher score, and a failover target must be at least as high as its primary. Decide your classification before you create providers, because fixing it afterwards means touching every grant. `[docs]` `[stack]`
- **Catalogs and the approval flow.** In Enterprise, a new provider is invisible until it is published to a catalog, and an App credential is inert until an administrator activates it. This is deliberate separation of "submit" from "publish"; plan who holds `llms:publish`. `[docs]` `[stack]`

---

## 3. Which edition do you need?

Community Edition is free and has no licence key. Enterprise Edition needs `TYK_AI_LICENSE` from Tyk. Both are self-managed and the switch between them keeps the database (a scripted image swap does it in about 20 seconds). `[docs]` `[stack]`

Map your Portkey usage to the edition that enforces it:

| If you use this in Portkey | Community | Enterprise |
|---|---|---|
| OpenAI-compatible proxy, streaming, model discovery, Anthropic passthrough | ✅ | ✅ |
| Fallback (`strategy.mode: fallback`, `retry`) | ✅ failover | ✅ |
| Load balancing (`loadbalance`, `weight`) | ❌ | ✅ Model Router |
| Conditional routing by content | ❌ | ✅ Semantic Router |
| Simple cache | ✅ plugin | ✅ |
| Semantic cache | ❌ | ✅ plugin |
| Guardrails that block or redact | ❌ filters are stored but **not executed**; content passes through with a warning | ✅ |
| Budgets that block traffic | ❌ tracked and reported, **never blocks** | ✅ `403 budget_exceeded` |
| Workspaces, per-team visibility | ❌ one Default catalog per type | ✅ Teams and catalogs |
| RBAC beyond "admin or not" | ❌ | ✅ Owner, Administrator, Editor, Viewer, Auditor, custom roles |
| SSO | ❌ | ✅ OIDC, SAML, LDAP |
| Audit logs, webhooks | ❌ | ✅ |
| MCP servers from an existing Tyk Gateway | ❌ | ✅ |
| Edge gateways, Prometheus metrics, analytics, tools, data sources, chat, portal | ✅ | ✅ |

All rows `[docs]`; the enforcement behaviours of filters and budgets were also observed `[stack]`.

The honest summary: if you came to Portkey for governance (guardrails, budgets, workspaces), you need Enterprise. If you came for a single OpenAI-compatible endpoint with failover and cost visibility, Community does it.

---

## 4. Before you start: inventory your Portkey estate

Portkey's Admin API exports everything except credentials. Run these with an **organisation admin key** (workspace keys are scoped to one workspace). All endpoints live under `https://api.portkey.ai/v1` with the header `x-portkey-api-key`. `[docs]`

```bash
export PK="https://api.portkey.ai/v1"; export PKH="x-portkey-api-key: $PORTKEY_ADMIN_KEY"
mkdir -p portkey-export && cd portkey-export
curl -s "$PK/workspaces"   -H "$PKH" > workspaces.json
curl -s "$PK/api-keys"     -H "$PKH" > api-keys.json
curl -s "$PK/integrations?page_size=100" -H "$PKH" > integrations.json
curl -s "$PK/providers"    -H "$PKH" > providers.json
curl -s "$PK/virtual-keys?page_size=100" -H "$PKH" > virtual-keys.json   # deprecated but still answers
curl -s "$PK/configs"      -H "$PKH" > configs-index.json
curl -s "$PK/prompts"      -H "$PKH" > prompts-index.json
curl -s "$PK/guardrails"   -H "$PKH" > guardrails.json
curl -s "$PK/policies/usage-limits" -H "$PKH" > usage-limits.json
curl -s "$PK/mcp-servers"  -H "$PKH" > mcp-servers.json
```

The config index does not include bodies, and the prompt index does not include templates. Fetch each one: `[docs]`

```bash
for slug in $(jq -r '.data[].slug' configs-index.json); do curl -s "$PK/configs/$slug" -H "$PKH" | jq '.data.config' > "config-$slug.json"; done
for id in $(jq -r '.data[].id' prompts-index.json); do curl -s "$PK/prompts/$id" -H "$PKH" > "prompt-$id.json"; done
```

What you will and will not get:

- **You get** every Config body, every prompt template (`string`), its `parameters`, `model`, `tools` and version, every usage-limit policy with its `credit_limit`, `type`, `periodic_reset` and `alert_threshold`, and each virtual key's `usage_limits` and `rate_limits`. `[docs]`
- **You do not get** any provider API key. Integrations return slug, provider and status only. You need the original vendor keys from your own vault to recreate them in Tyk. If you do not have them, rotate them at the vendor now; you should rotate them at cutover anyway, because they lived in Portkey. `[docs]`
- **Logs** are exportable only on the Enterprise plan, as JSONL, at most 50,000 rows per export job, through `POST /v1/logs/exports`, then `POST .../{id}/start` and `GET .../{id}/download`. Export what you need for compliance retention before you cancel. `[docs]`

Make a one-page table from this: each Config (and the API keys that use it), the targets it references, which guardrails it attaches, which prompts the application calls, and the budgets on each key. Section 6 walks that table.

Also record which **request surfaces** your applications use. Grep your codebases for these and tick them off:

| Portkey surface | Tyk AI Studio 2.2.2 status |
|---|---|
| `POST /v1/chat/completions` | ✅ Main Ingress `[docs]` |
| `POST /v1/completions` | ✅ legacy completions on the Main Ingress `[docs]` |
| `GET /v1/models` | ✅ returns exactly what the App may call `[docs]` `[stack]` |
| `POST /v1/messages` (Anthropic format) | ✅ `/llm/call/{slug}/v1/messages` passthrough for direct Anthropic; `/anthropic/{slug}/v1/messages` for **Bedrock** providers only `[docs]` `[stack]` |
| `POST /v1/embeddings` | ⚠️ Not on `/v1` or `/ai` (both answer `404`). Works through the vendor-native passthrough `/llm/call/{slug}/v1/embeddings` for OpenAI-compatible providers; see 6.11 `[stack]` |
| `POST /v1/responses` | ❌ in 2.2.2; the unreleased 2.3.0 changelog lists OpenAI Responses, Conversations, Batches and Files via `/llm/` passthrough `[docs]` |
| Images, audio, moderations, files, fine-tuning, batches, realtime | ❌ not documented. The `/llm/call/{slug}/...` passthrough forwards the vendor's own API untouched (verified for OpenAI embeddings and Anthropic `count_tokens` `[stack]`), so other vendor-native paths may work `[unconfirmed]` |
| `/prompts/{id}/completions`, `/prompts/{id}/render` | ❌ gap, see 6.8 |
| `/feedback` | ❌ gap |
| `/v1/decisions` | ❌ in 2.2.2; 2.3.0 changelog lists a "Decision models" endpoint `[docs]` |
| `wss://.../v1/realtime` | ❌ |

---

## 5. Stand up Tyk AI Studio v2.2.2

### 5.1 Pin the version

Docker Hub tags for `tykio/tyk-ai-studio`, `tykio/tyk-ai-studio-ent`, `tykio/tyk-microgateway` and `tykio/tyk-microgateway-ent` all have `v2.2.2` (pushed 12 October 2026) as the highest stable tag; `v2.3.0-unstable.*` pre-releases started on 20 October. Pin `v2.2.2` explicitly. The `latest` tag on the hub image was last pushed on 17 September 2026 from a commit-hash build that predates 2.2.0, so do not use it. `[docs]`

2.2.2 matters even though AI Studio itself is unchanged from 2.2.1: it removes an unauthenticated token endpoint on the microgateway that allowed anyone with network access to mint an admin token and load a plugin. Edge gateways no longer serve any `/api/v1` path; standalone microgateways mint tokens with `POST /api/v1/tokens` or `microgateway -create-admin-token`. If you ever ran a 2.2.1 or older edge reachable from an untrusted network, read the "What to check" section of the 2.2.2 changelog before migrating traffic onto it. `[docs]`

### 5.2 Topology

AI Studio is **hub-and-spoke**: `[docs]`

- The **hub** (`tyk-ai-studio`) holds configuration, the admin console, the AI Portal, chat, the management API on port 8080 (the workshop stack maps it to 4000), a gRPC control endpoint on 50051, and an **embedded gateway** on 9090.
- **Edge gateways** (`tyk-microgateway`, `GATEWAY_MODE=edge`) receive configuration over gRPC, cache it in local SQLite, serve traffic on port 8080 (mapped to 9091 here), report analytics back, and keep serving if the hub is unreachable. Configuration changes are not live on an edge until you **push** (`Edge Gateways > Push Configuration`, or `POST /api/v1/edges/reload-all`).

Plan production traffic through edge gateways. The architecture page describes the embedded gateway as a testing and chat gateway with "no filters, no middleware, no plugins", and only edge gateways route through Model Routers and run auth plugins. The release notes are more nuanced: tool filters run "on AI Studio and on Edge Gateways", the embedded gateway "does not run authentication plugins, and still accepts App keys", and a 2.2.0 fix concerned the embedded gateway letting an App overspend its budget for a few minutes, so budgets are checked there too. `[docs]` On the 2.2.2 Enterprise workshop stack used for this guide the embedded gateway ran failover, guardrail filters (redaction and blocking) and the zero-budget check, while a router model string returned `403` there and routed only on the edge `[stack]`. Treat the edge as the only supported production data plane; it is also where the 9,000 requests-per-second figure in the 2.2.0 release notes was measured. `[docs]`

Edges receive LLM providers, Apps, filters, plugins, Model Routers and data sources (with all four data-source endpoints available on the edge) `[docs]`; on the workshop stack, model prices, tools and their MCP endpoint were served from the edge as well after a push `[stack]`. Chats and users stay on the hub. `[docs]`

### 5.3 Minimum production settings

| Variable | Purpose |
|---|---|
| `TYK_AI_LICENSE` | Enterprise licence (JWT). Omit for Community `[docs]` |
| `TYK_AI_SECRET_KEY` | Key for encrypting Secrets. **Changing it later makes every stored secret unreadable** `[docs]` `[stack]` |
| `MICROGATEWAY_ENCRYPTION_KEY` | 32 hex characters, encrypts configuration pushed to edges `[docs]` |
| `DATABASE_TYPE` / `DATABASE_URL` | SQLite is the default; use PostgreSQL 14 or later for production `[docs]` |
| `QUEUE_TYPE=nats`, `NATS_URL` | NATS JetStream for multi-instance hubs `[docs]` |
| `SITE_URL` | Public URL of the console (SSO callbacks, portal links) `[docs]` |
| `METRICS_AUTH_TOKEN` or `METRICS_ALLOW_UNAUTHENTICATED=true` | `/metrics` is not registered without one of these since 2.2.0 `[docs]` |
| `ENABLE_TRACING=true`, `TRACING_ENDPOINT` | OTLP gRPC span export `[docs]` |
| `GATEWAY_SERVER_TIMING=true` | `Server-Timing` header for latency analysis; not for permanent production use `[docs]` |
| `LLM_UPSTREAM_ALLOWED_HOSTS` | Allow-list of upstream hosts the gateway may call `[docs]` |
| `EDGE_TLS_CA_PATH`, `EDGE_TLS_SERVER_NAME` | Edge to hub TLS (2.2.1 requires TLS 1.2 or later on the gRPC link) `[docs]` |

Deployment options are Docker Compose (official `quickstart/ce` and `quickstart/enterprise` compose files), a Helm chart in the `helm/` directory of the source repository, and DEB/RPM packages. Air-gapped operation is not documented: the plugin marketplace needs an OCI registry or cache, and Enterprise licence telemetry is on by default (`LICENSE_DISABLE_TELEMETRY`). `[docs]`

For a sandbox, the official quickstart compose files give you a hub and an edge. This guide was verified on a workshop stack that adds a mock OpenAI-compatible LLM and Qdrant, pinned to `v2.2.2`.

### 5.4 First administrator

The first registered user becomes the administrator (`ADMIN_EMAIL` is deprecated). Create your own user API key under your profile; the management API accepts it as `Authorization: Bearer <key>`. Bodies use the JSON:API envelope `{"data":{"type":"<type>","attributes":{...}}}`. `[docs]` `[stack]`

Throughout section 6, `$AIS` is the hub URL and `ais` is a helper that adds the bearer header:

```bash
export AIS=http://localhost:4000; export AIS_KEY=<your user API key>
ais() { curl -s -H "Authorization: Bearer $AIS_KEY" -H "Content-Type: application/json" "$@"; }
```

---

## 6. Migration, step by step

Each step says what the Portkey object was, what it becomes, how to create it, and what changes semantically. Appendix B carries one worked example from end to end.

### 6.1 Provider credentials

**Portkey:** an Integration holds the vendor key at organisation level; each workspace gets an AI Provider with a slug, a model allow-list and optional budget and rate limits. Requests name it as `@slug/model`. `[docs]`

**Tyk:** a **Secret** holds the key; an **LLM provider** references it, scopes models with a regex, carries a privacy level and (Enterprise) is published to one or more catalogs. `[docs]`

1. **Create the secret.** `Settings > Secrets > Add`, name `ANTHROPIC_KEY`, paste the vendor key. Or:

   ```bash
   ais -X POST $AIS/api/v1/secrets -d '{"data":{"type":"secrets","attributes":{"var_name":"ANTHROPIC_KEY","value":"sk-ant-..."}}}'
   ```

2. **Create the provider.** `LLM management > LLM providers > Add`. The equivalent call: `[stack]`

   ```bash
   ais -X POST $AIS/api/v1/llms -d '{"data":{"type":"llms","attributes":{
     "name":"Anthropic Prod","vendor":"anthropic","api_endpoint":"https://api.anthropic.com/v1",
     "api_key":"$SECRET/ANTHROPIC_KEY","default_model":"claude-sonnet-5-5",
     "allowed_models":["^claude-.*$"],"privacy_score":75,"active":true}}}'
   ```

   The slug is derived from the name (`anthropic-prod`), and that slug is what applications type in model strings. Choose names you are happy to live with. `[stack]` For Bedrock the credentials are not `api_key`: the AWS access key, secret key and optional session token are stored in the provider's `metadata` map (the console's AWS fields), each as a `$SECRET/...` reference. `[docs]`

3. **Map vendors.** Documented vendor values are `openai`, `anthropic`, `bedrock`, `vertex`, `google_ai`, `huggingface` and `ollama`. `[docs]`

   | Portkey provider | Tyk vendor | Notes |
   |---|---|---|
   | `openai` | `openai` | |
   | `anthropic` | `anthropic` | Direct Anthropic. The Main Ingress translates OpenAI-shaped requests to the Messages API `[stack]` |
   | `bedrock` | `bedrock` | Access key, secret and optional session token go in the provider's AWS fields, each as `$SECRET/...` `[docs]` |
   | `vertex-ai` | `vertex` | **Not served on `/v1` or `/ai`** (`unsupported_vendor`); only through `/llm/call/{slug}` `[docs]` |
   | `google` (Gemini API) | `google_ai` | |
   | `huggingface` | `huggingface` | Same `/v1` restriction as Vertex `[docs]` |
   | `ollama` | `ollama` | |
   | `azure-openai` | not listed | The marketing site claims Azure OpenAI support but the LLM management docs do not name it. Try vendor `openai` with the deployment URL and test; Azure's `api-key` header and `api-version` query differ from OpenAI's `[unconfirmed]` |
   | `groq`, `mistral-ai`, `together-ai`, `openrouter`, `deepseek`, vLLM, any OpenAI-compatible server | `openai` with a custom **API Endpoint** | This is how the workshop's mock LLM is registered and it works on the Main Ingress `[stack]` |

   Portkey's `custom_host` per target becomes a separate provider per host. Portkey's `forward_headers` has no equivalent; if an upstream needs extra headers you need a plugin `[unconfirmed]`.

4. **Allowed models.** Portkey's "Allowed Models" list becomes `allowed_models`, a list of regular expressions. `^gpt-5.*$` rather than a literal list. `[docs]`

5. **Privacy level.** Set it now (section 2). Public cloud vendors under a data processing agreement are typically Confidential (51–75); a self-hosted model can be Restricted (76–100). `[stack]`

6. **Enterprise only: publish.** New providers are not added to any catalog automatically. `Catalogs > LLM catalogs > <catalog> > Add`, or `POST /api/v1/catalogues/{id}/llms/{llmId}`. Until you do this no one sees the provider in the Portal or the chat. `[docs]` `[stack]`

### 6.2 Model prices

Portkey ships pricing for its catalog and computes cost automatically. Tyk computes cost from **model prices** you enter: exact model name, vendor, input, output, cache-write and cache-read prices, currency. The console form takes prices per million tokens; the API takes them **per token** (`cpit` input, `cpt` output, `cache_write_pt`, `cache_read_pt`) and rejects anything above 0.01 per token. The lookup is exact-match, so a price for `claude-sonnet-5-5` does not cover `claude-sonnet-5-5-20260501`. `[docs]` Without a price a request is recorded with zero cost, and **a currency budget cannot accumulate spend it never saw**. `[stack]`

```bash
# Claude Sonnet 5.5 at $2 / $10 per million tokens, written per token
ais -X POST $AIS/api/v1/model-prices -d '{"data":{"type":"model-prices","attributes":{"model_name":"claude-sonnet-5-5","vendor":"anthropic","cpit":0.000002,"cpt":0.00001,"currency":"USD"}}}'
```

Attribute names are from the management API's OpenAPI document and the workshop stack's seed script `[docs]` `[stack]`. The Community **LLM Price Sync** marketplace plugin can keep common vendor prices current. `[stack]`

### 6.3 Consumers: workspaces, API keys and metadata

**Portkey:** workspaces own API keys; a key may carry a default Config and metadata; `x-portkey-metadata` adds per-request attribution. `[docs]`

**Tyk:** three objects. `[docs]` `[stack]`

- A **Team** is a group of users. It receives catalogs (which providers, tools and data sources its members may see) and, in Enterprise, roles and a Team budget.
- A **catalog** is a published set of providers (or tools, or data sources).
- An **App** is one calling application. It has exactly one credential and a list of grants. A developer creates it in the AI Portal; an administrator activates the credential.

Translate:

| Portkey | Tyk |
|---|---|
| Workspace `contact-centre` | Team `Contact Centre` with LLM catalog `Contact centre models`, tool catalog, data catalog |
| Workspace manager | Role `Editor` (or a custom role) assigned to the Team or user |
| Service API key `compass-backend-prod` | App `Compass Backend`, owned by the service's engineer, grants = the providers it used |
| User API key | Personal App, or a User API key if the person needs the management API |
| Metadata `_user`, `team`, `env` | Encode as separate Apps (`Compass Backend (staging)`, `Compass Backend (prod)`) and Teams. There is no per-request metadata on proxy traffic |

Create an App and activate it in one go: `[stack]`

```bash
APP=$(ais -X POST $AIS/api/v1/apps -d '{"data":{"type":"apps","attributes":{"name":"Compass Backend","description":"Contact centre assistant backend","llm_ids":[1,2],"user_id":1}}}')
APP_ID=$(echo $APP | jq -r .data.id); CRED_ID=$(echo $APP | jq -r .data.attributes.credential_id)
ais -X POST $AIS/api/v1/apps/$APP_ID/activate-credential
ais $AIS/api/v1/credentials/$CRED_ID | jq -r .data.attributes.secret     # hand this to the service owner once
```

Two behaviours to brief application teams on:

- **Grants are enforced per request.** A model string for a provider the App was not granted returns `403`. `GET /v1/models` with the App secret lists exactly what it may call, which makes a good smoke test. `[docs]` `[stack]`
- **`PATCH /api/v1/apps/{id}` replaces omitted fields.** A PATCH carrying only `monthly_budget` emptied the App's `llm_ids` on 2.2.2, and the next gateway call failed with a grants error rather than a budget error. Send the full attribute set or use the console. `[stack]`

### 6.4 Gateway Configs: routing, retries and timeouts

This is the step that takes the most thought, because one Portkey Config becomes several Tyk objects. Start from this representative Config:

```json
{
  "retry": { "attempts": 3, "on_status_codes": [429, 503], "use_retry_after_headers": true },
  "cache": { "mode": "simple", "max_age": 3600 },
  "request_timeout": 30000,
  "strategy": { "mode": "loadbalance" },
  "targets": [
    { "provider": "@anthropic-prod", "weight": 0.7, "override_params": { "model": "claude-sonnet-5-5" } },
    { "weight": 0.3,
      "strategy": { "mode": "fallback", "on_status_codes": [429, 500, 502, 503] },
      "targets": [
        { "provider": "@openai-prod", "override_params": { "model": "gpt-5" } },
        { "provider": "@bedrock-eu",  "override_params": { "model": "anthropic.claude-sonnet-5-5-v1:0" } }
      ] }
  ],
  "input_guardrails": ["gr-pii-check"],
  "output_guardrails": [{ "id": "gr-no-promises", "deny": true }]
}
```

Decompose it:

**`fallback` → Failover on the provider.** Open the primary provider, **Failover > Add fallback**, choose the fallback provider and model, order them. Rules: at most 10 fallbacks; each must be active, in the same namespace or global, with privacy level at least that of the primary; a `401` or `403` never triggers failover; streaming can only fail over before the first token. Default triggers are `408, 429, 500, 502, 503, 504`, timeout and connection error; you may remove codes, add only 5xx codes, `408` and `429`, and set a per-attempt timeout. `[docs]` The API shape on 2.2.1, not yet in the published OpenAPI document: `[stack]`

```bash
ais -X PATCH $AIS/api/v1/llms/$OPENAI_ID -d '{"data":{"type":"llms","attributes":{ ...full attributes..., "failover":{"targets":[{"llm_id":'$BEDROCK_ID',"model":"anthropic.claude-sonnet-5-5-v1:0"}],"triggers":{"status_codes":[429,500,502,503],"on_timeout":true,"on_connection_error":true,"timeout_seconds":30}}}}}'
```

On 2.2.2 the `failover` object is accepted on `POST` and `PATCH`, although `timeout_seconds` was not echoed back in the stored triggers `[stack]`. Responses carry `X-Tyk-Served-LLM`, `X-Tyk-Served-Model` and `X-Tyk-Failover: true`; analytics record `failover_attempt` and the metric `aistudio_llm_failover_total` counts attempts. Fallback spend counts against both the App budget and the fallback provider's budget. `[docs]` `[stack]`

Semantic difference: Portkey's fallback is a property of the *request* (any target list). Tyk's is a property of the *provider*: every request to `openai-prod` inherits its waterfall, whoever sends it. If two applications need different fallback chains from the same vendor key, create two providers referencing the same `$SECRET`. `[stack]`

**`loadbalance` + `weight` → Model Router (Enterprise, edge only).** `LLM management > Model Routers > Create`: slug `compass`, a pool matched by a model-name glob (`compass-*`), algorithm `weighted` or `round_robin`, vendors with weights and a model mapping per vendor (`compass-chat → claude-sonnet-5-5` on Anthropic, `compass-chat → gpt-5` on OpenAI). Applications call `compass/compass-chat`. Publish the router to a catalog, grant it to the App, push to the edge. Responses carry `X-Tyk-Router`, `X-Tyk-Route` and `X-Tyk-Route-Reason`. A Model Router does not retry failures; the failover list of the provider it picked does that. Without an Enterprise licence the router endpoints answer `402`. `[docs]` `[stack]`

`weight` is an integer in the API schema, and a fractional weight is rejected (`cannot unmarshal number 0.7 ... of type int`). Express Portkey's 0.7 and 0.3 as 7 and 3. `[docs]` `[stack]`

**`conditional` → Semantic Router or separate model strings.** Portkey routes on `metadata.*`, `params.*` or `url.pathname`. Tyk has no request metadata, so:

- Conditions on *what the prompt is about* become a **Semantic Router** (Enterprise, edge only): routes with keywords or regex, example prompts matched by embeddings, or an LLM judge, with a default route, session affinity, and a **shadow** mode that records the decision without acting on it. Applications call `{slug}/auto`. `[docs]` `[stack]`
- Conditions on *who is calling* (`metadata.team`, `metadata.env`) become different Apps with different grants, or different model strings chosen in code.
- Conditions on `params.model` are already covered by the Main Ingress model string.

**`retry` → failover triggers, with a caveat.** Tyk does not retry the same target. A `429` from the primary goes straight to the first fallback. If your Portkey retry policy existed to ride out short rate-limit bursts on one provider, add a second provider pointing at the same vendor key as the first fallback: the request is retried once, on a fresh connection, against the same upstream `[stack]`. `use_retry_after_headers` has no equivalent `[docs]`.

**`request_timeout` → per-attempt timeout** in the failover triggers (`timeout_seconds`). It applies per attempt, not to the whole waterfall. `[docs]`

**`cb_config` → nothing.** No circuit breaker is documented. A failing primary is tried on every request and failed over each time; the cost is one failed upstream call per request until it recovers.

**`override_params`, `default_params`, `drop_params` → mostly the application's job.** The model is set by the model string or router mapping. Other parameters are passed through as sent. **LLM call settings** (`/api/v1/llm-settings`) hold temperature, max tokens and similar for chat experiences; whether they are applied to proxy traffic is not documented `[unconfirmed]`. If you relied on Portkey to strip or force parameters, do it in a script filter (which can rewrite the request payload) or in code. `[docs]`

**`strict_open_ai_compliance: false`** has no toggle. For vendor-only features use the vendor-native passthrough `/llm/call/{slug}/...`. `[docs]`

**Guardrail references** move to the provider's **Filters** list; see 6.6.

### 6.5 Caching

| Portkey | Tyk |
|---|---|
| `cache.mode: simple`, `max_age` | **LLM Response Cache** plugin from the Community marketplace, attached to the provider under **Plugins**; exact-match. Response header `X-Cache-Status: HIT` `[docs]` `[stack]` |
| `cache.mode: semantic` | **Advanced LLM Cache** plugin (Enterprise): exact match first, then cosine similarity (default threshold 0.95) on the last user message against an embedding provider you configure; in-memory or Redis 8 / Redis Stack backend. Headers `X-Cache-Status`, `X-Cache-Match: semantic`, `X-Cache-Similarity` `[docs]` `[stack]` |
| `x-portkey-cache-force-refresh` | Request header `X-Cache: bypass` (both plugins; the Community plugin also accepts `?cache=bypass`) or `X-Cache: exact-only` (Advanced) `[docs]` |
| `x-portkey-cache-namespace` | No per-request namespace header. Partitioning is a plugin setting: by API key hash, App or organisation `[docs]` |

Plugins are installed from `Plugins > Marketplace`, their scopes approved, attached per provider, then pushed to the edge. Cache TTL and backend are plugin settings. `[stack]`

### 6.6 Guardrails become filters

**Portkey:** a guardrail is a list of checks; it is attached through `input_guardrails` / `output_guardrails` in a Config; each has `deny` (default false), `async` (default true, so it cannot block), and feedback on pass or fail. A failed-but-not-denied check returns status `246`; a denied one returns `446`. `[docs]`

**Tyk (Enterprise):** a **filter** is either a **script** (Tengo) or a **guardrail** (no code, backed by a detector). It is attached to an LLM provider (ordered list), a chat experience, or a tool, in request or response direction, and runs **synchronously** in the gateway. Actions are **Block**, **Redact** or **Log**. Every hit can raise a **compliance event** (type, severity, description, metadata; guardrail events never carry the matched text, script events carry whatever the script puts in `metadata`) visible in the compliance dashboard (`/admin/compliance`, labelled **Governance > Compliance overview** in the console) and at `GET /api/v1/compliance/events`. In Community, filters are stored but **not executed**. `[docs]` `[stack]`

Map the checks:

| Portkey check | Tyk filter |
|---|---|
| Regex Match, Contains, Ends With, Word/Sentence/Character Count, Uppercase/Lowercase, Not Null | Script filter: `text.re_match`, `text.contains`, `len`, `text.to_lower` on `input.messages` |
| JSON Schema, JSON Keys, Valid URLs | Script filter with the `json` module (`json.decode`); response filters are block-only |
| Detect PII (Pro) | Guardrail, provider **Built-in pattern library**, detector `pii`, action Redact (placeholder, mask or hash) or Block; or **Microsoft Presidio**, **Azure AI Language PII** |
| Prompt injection (partner) | Guardrail, built-in detector `injection` (heuristics), or **Lakera Guard** |
| Moderate Content (Pro), Azure Content Safety, Bedrock Guardrails | Guardrail with the same external provider (Azure AI Content Safety, Amazon Bedrock Guardrails) |
| Secrets, credentials | Guardrail built-in detectors `secrets` (request) and `leak` (response) |
| Webhook (bring your own) | Guardrail provider **HTTP classifier**, or `tyk.makeHTTPRequest(method, url, headers, body)` from a script |
| LLM-based judge | `tyk.llm(llm_id, settings, prompt)` from a script (30 s timeout by default) |
| Model Whitelist / Allowed Models | `allowed_models` on the provider plus App grants; no filter needed |
| Required Metadata Keys | No equivalent (no request metadata) |
| Request Parameters Check | Script filter on `input.raw_input` |

All rows `[docs]`. Observed on 2.2.2: the built-in redactor writes typed placeholders such as `[REDACTED:EMAIL]` and `[REDACTED:PHONE_US]`, and compliance events carry typed names such as `guardrail.pii.email` and `guardrail.secrets.aws_access_key` with the filter name and action `[stack]`. The first Enterprise start seeds four unattached guardrails you can reuse: *Credentials in prompts (block)*, *Personal data before the vendor (redact)*, *Prompt injection heuristics (log)* and *Credential leakage in responses (block)*; `SKIP_FILTER_DEFAULTS=true` disables the seeding. `[docs]` `[stack]`

Semantic differences worth a line each in your runbook: `[docs]`

- **Async checks disappear.** Everything runs inline. Portkey's "log but never block" becomes action **Log**. Script execution is capped at `FILTER_SCRIPT_TIMEOUT` (5 s).
- **Failure modes are fixed.** Request filters that time out block the request. Response filters fail open. Tool filters fail closed with a generic `403` and the reason only in the logs and compliance event.
- **Response filters cannot modify**, only block. Redaction of model output is not available; redact on the way in instead.
- **Streaming responses** are checked chunk by chunk with `current_buffer` holding the accumulated text and a final pass with `is_final: true`. Chunks already sent cannot be recalled.
- **Status codes.** A blocked tool call returns `403` with a generic "blocked by policy" message `[docs]`. A blocked LLM request returns HTTP `400` with an OpenAI-shaped `invalid_request_error` whose message names the filter: `Policy error: Credentials in prompts (block) - Request blocked by policy` `[stack]`. There is no "served but flagged" `246`.
- **Feedback on pass or fail** has no equivalent; compliance events are the audit record.

A script filter skeleton, the shape that passed on 2.2.1: `[stack]`

```tengo
text := import("text")
tyk := import("tyk")
// Declare output once at top level; a ":=" inside an if-block makes a block-local variable.
output := { block: false, payload: "", message: "", compliance_events: [] }
for msg in input.messages {
    if msg.role != "user" { continue }
    if text.re_match("\\b\\d{3}-\\d{2}-\\d{4}\\b", msg.content) {
        output = { block: true, payload: "", message: "SSN in prompt",
                   compliance_events: [{ event_type: "policy_violation", severity: "critical", description: "SSN in prompt" }] }
        break
    }
}
```

Create it with `POST /api/v1/filters`, `kind: "script"`, `response_filter: false`, and the script **base64-encoded** in `script`; attach it with `"filters": [<id>]` on the provider (a full-attribute `PATCH` of the LLM, for the reason given in 6.3). Test in the console's **Test** panel. The API behind it, `POST /api/v1/filters/test`, takes the script as **plain text** (unlike the create endpoint, which wants base64) plus a raw `input` map, and does not build the normalised `messages` from a chat body for you. `[stack]`

### 6.7 Budgets and rate limits

**Portkey:** usage-limit policies and per-key or per-provider limits in cost (minimum $1) or tokens (minimum 100), reset weekly or monthly, with an alert threshold; rate limits in requests or tokens per minute, hour or day; conditions and `group_by` across keys, providers, models and metadata. `[docs]`

**Tyk:** a **budget** is an amount in a currency per month at one of four scopes: organisation, LLM provider, App, Team. `null` means no limit; `0` blocks everything (this flipped in 2.2.0; integrations that sent `monthly_budget: 0` for "no limit" must now send `null`). Alerts fire once per period at 80% and 100% to the App owner and administrators (in-app, and by email with SMTP configured `[stack]`), and as `budget.team.threshold` webhook events for Teams. Enforcement is Enterprise: `403` with OpenAI error code `budget_exceeded`, `503 budget_check_unavailable` if the check cannot run, `403 app_inactive` for a deactivated credential. Edges learn spend through a periodic budget pulse (30 seconds for Team blocks). Community tracks and reports but never blocks. `[docs]` `[stack]`

Translate:

| Portkey limit | Tyk |
|---|---|
| Cost limit on a workspace API key | App monthly budget (`monthly_budget`, `budget_start_date` on the App) |
| Cost limit on an Integration or AI Provider | LLM provider monthly budget |
| Workspace-wide cost limit | **Team budget** (Enterprise): a monthly pool, a default allocation per new App, alert-only or alert-and-block; `GET /api/v1/analytics/team-costs` |
| Organisation-wide | Organisation budget |
| Token-denominated limit | No equivalent. Convert to currency with your model prices |
| Weekly reset | No equivalent. Monthly only; `POST /api/v1/apps/{id}/reset-budget` restarts an App's period today (it answers `400 app does not have a budget configured` when there is no positive budget `[stack]`) |
| Alert threshold other than 80% | No equivalent |
| RPM / TPM rate limits | Not in the core. Options: the Community **LLM rate limiting** plugin (rules limiting requests, tokens or concurrent requests per window, keyed by App, user, model, LLM, API key or globally; synced to edges; added in 2.1.0), or put a Tyk API Gateway in front for classic quotas and `429`s. Edge-gateway built-in rate-limit settings were removed in 2.2.0 |

All rows `[docs]`; Team budgets and `budget_exceeded` behaviour also `[stack]`.

Prices come first: a budget without model prices sees zero spend (6.2).

### 6.8 Prompt templates and partials

This is the largest functional gap. Portkey's Prompt Engineering Studio stores Mustache templates with variables, partials, immutable versions and labels (`production`, `staging`, custom), and serves them at runtime through `/prompts/{id}/completions` and `/prompts/{id}/render`. `[docs]`

Tyk AI Studio 2.2.2 has no prompt library and no runtime prompt endpoint. What exists: `[docs]`

- **Chat experiences** have a system prompt and a per-room list of **prompt templates** for the built-in chat UI. These are not reachable by API clients.
- The Enterprise **Asset Catalog** plugin (v1.2.0, needs AI Studio 2.2.1 or later) registers prompts, agents and applications as governed, versioned catalog records with owners and risk tiers, but "AI Studio does not proxy these assets itself" and there is no documented retrieval endpoint.

Recommended approach:

1. Export every template (section 4). The `string` field holds the Mustache source; `parameters` holds model settings; `tools` holds function definitions.
2. Move templates into version control next to the application, keep the Mustache syntax, and render client-side with a Mustache library (`chevron` or `pystache` in Python, `mustache` in Node). Partials become files included at build time.
3. Replace `prompt_id@label` with your deployment pipeline: `production` is whatever is on the main branch, `staging` is a branch or a feature flag.
4. Replace `/prompts/{id}/completions` with a plain `/v1/chat/completions` call carrying the rendered messages and the `parameters` from the export.
5. If you need an organisational register of which prompt is live where, record it in the Asset Catalog so it shows up in governance reports, and link the version to the git commit.

The drop-in behaviours you lose: editing a prompt in a UI without a deploy, A/B by label, and prompt-level observability (Portkey's "prompt slug" column). If any of these is a hard requirement, keep a thin prompt service of your own in front of Tyk.

### 6.9 Observability

| Portkey | Tyk AI Studio | Notes |
|---|---|---|
| Logs with request and response bodies | **Proxy logs** per App and per provider. Bodies are stored only when the edge sets `ANALYTICS_STORE_REQUESTS` and `ANALYTICS_STORE_RESPONSES` (default `false`, truncated to `ANALYTICS_MAX_BODY_SIZE`; documented in the source repository's microgateway configuration, not on tyk.io); `dont_log_bodies` per provider turns them off for sensitive providers | `[docs]` `[stack]` |
| Analytics dashboards (cost, tokens, latency, cache hit rate) | **Analytics**: requests, tokens, cost per App, provider, model, Team; `/api/v1/analytics/*` endpoints (`cost-analysis`, `token-usage-per-app`, `total-cost-per-vendor-and-model`, `budget-usage`, `team-costs`, and others) | `[docs]` |
| Retention: 3 days (Developer), 30 days (Production), custom (Enterprise) | Hub retention is whatever you apply to your own PostgreSQL; no hub setting is documented. The edge prunes its local analytics with `ANALYTICS_RETENTION_DAYS` (7 days with the analytics pulse, otherwise 90) | `[docs]` |
| Traces: `x-portkey-trace-id`, span headers, `traceparent` | W3C `traceparent` is read and forwarded to the vendor even with tracing off; with `ENABLE_TRACING=true` and `TRACING_ENDPOINT`, one span per LLM call named `{operation} {model}` with `gen_ai.*` attributes is exported over OTLP gRPC; service names `tyk-ai-studio` and `tyk-microgateway` | No HTTP OTLP, no sampling setting documented `[docs]` |
| OTel ingest (`/v1/otel`) from your own apps | None. Send your application spans to your collector directly; join on `traceparent` | `[docs]` |
| Prometheus (OSS gateway 1.14+) | `/metrics` with `gen_ai_server_request_duration_seconds`, `gen_ai_server_time_to_first_token_seconds`, `gen_ai_server_time_per_output_token_seconds`, `gen_ai_client_token_usage`, plus `aistudio_llm_requests_total`, `aistudio_llm_failover_total`, `aistudio_policy_blocks_total` (and, seen on the 2.2.2 edge, `aistudio_compliance_events_total`, `aistudio_guardrail_latency_seconds`, `aistudio_llm_inflight_requests`). Requires `METRICS_AUTH_TOKEN` or `METRICS_ALLOW_UNAUTHENTICATED=true` | `[docs]` `[stack]` |
| Latency breakdown | `Server-Timing` header (`gw-pre`, `upstream-ttfb`, `upstream`, `gw`, `gw-ttfb`, `total`, `elapsed`, `conn`, `attempts`) with `GATEWAY_SERVER_TIMING=true` | `[docs]` `[stack]` |
| `x-portkey-metadata`, `_user` | None on proxy traffic. Chat records carry the user; App identity is on every proxy log; 2.2.1 adds `on_behalf_of` and `acting_agent` when an auth plugin authenticates a delegated call | `[docs]` |
| Feedback API | None | Gap |
| Log export | Audit and compliance exports (CSV/JSON); analytics API; query the PostgreSQL tables directly if you need bulk proxy logs | No bulk export endpoint documented `[docs]` |
| Alerts | In-app notifications, SMTP email, outbound **webhooks** (Enterprise) with HMAC-SHA256 signatures, retries and dead-letter replay | `[docs]` `[stack]` |

Portkey's `x-portkey-sensitive-headers` and its request id have no counterparts; the unreleased 2.3.0 changelog adds an `X-Tyk-AI-Request-ID` header. Portkey already accepts the W3C `traceparent` header, so clients that use it instead of `x-portkey-trace-id` need no tracing change at all. `[docs]`

### 6.10 Governance

| Portkey | Tyk AI Studio (Enterprise) |
|---|---|
| Organisation roles Owner / Admin / Member; workspace manager / member; per-key scopes | System roles **Owner, Administrator, Editor, Viewer, Auditor**; custom roles from `resource:action` permissions (`llms:read`, `llms:write`, `llms:publish`, `edges:execute`, ...); assignable to users or Teams; a `403` for a missing permission names it (for example `"permission": "llms:publish"`) `[docs]` `[stack]` |
| SSO: OIDC, SAML, JIT provisioning | **Identity providers**: OIDC, SAML, LDAP through the embedded Tyk Identity Broker; IdP groups map to Teams, so roles and catalogs follow directory membership; callback `SITE_URL/auth/<profile-id>/<provider>/callback` `[docs]` `[stack]` |
| SCIM (Okta, Azure AD) | None: "AI Studio has no SCIM endpoint". Group-to-Team mapping at every login is the mechanism `[docs]` |
| Audit logs (Enterprise), `GET /audit-logs` | **Audit trail**: every mutating management call and auth event with user, IP, action, resource, field-level diff with secrets redacted; CSV/JSON export of up to 50,000 records; JSON lines on disk for a SIEM; `AUDIT_RETENTION_DAYS` (default 90) `[docs]`; `GET /api/v1/audit/records` answered on 2.2.1 but is not in the published OpenAPI document `[stack]` |
| Compliance posture (SOC 2, ISO 27001, GDPR, HIPAA attestations for Portkey's SaaS) | Not applicable in the same way: AI Studio runs in your environment, so the attestations are yours. Tyk's own compliance documents cover Tyk as a vendor `[docs]` |
| Data residency | Wherever you deploy. Enterprise images send licence telemetry to Tyk unless `LICENSE_DISABLE_TELEMETRY=true` `[docs]` |
| None | **Governed metadata** (Enterprise): a schema of required fields (owner, lifecycle, risk tier, data classification) on every provider, tool and data source, advisory or enforced with a `422` on save `[docs]` `[stack]` |
| None | **Community submissions** in the Portal with attestation templates and a review queue `[stack]` |

### 6.11 MCP, tools, embeddings and data sources

**MCP.** Portkey's MCP Gateway proxies registered MCP servers at `mcp.portkey.ai/{server-slug}/mcp` with per-tool provisioning and logging. `[docs]` Tyk splits this: `[docs]` `[stack]`

- Any API you import from an **OpenAPI document** becomes a **tool** with an allow-list of operations, a privacy level, filters on arguments and results, and three access methods: chat, REST (`/tools/{slug}` with an `operation_id`; `403` for an operation not on the allow-list) and **MCP** (`/tools/{slug}/mcp`, for MCP clients such as Claude Desktop). New tools are chat-only until you switch REST or MCP on. `[docs]` On the stack: REST calls are `POST` with path and query values in `parameters` as a map of string lists, the MCP endpoint speaks Streamable HTTP, the App page prints the MCP client configuration, and the same URL worked from Claude Code with the App secret as bearer token. `[stack]`
- **Remote MCP servers** are registered as MCP proxies on a Tyk Dashboard, either a pass-through to an existing MCP endpoint (Tyk Gateway 5.13 or later) or a REST API converted to MCP (5.15 or later). AI Studio Enterprise connects to that Dashboard, imports the proxies under `Context management > MCP servers`, publishes them in the AI Portal and mints Tyk keys for Apps. Tyk Gateway stays on the data path, the traffic does not pass through AI Studio, and these servers are not usable from AI Studio chats. There is no Gateway-less registration of a remote MCP server. `[docs]`

**Embeddings.** Portkey proxies `/v1/embeddings` for many vendors. AI Studio 2.2.2 documents no OpenAI-style embeddings proxy. It has **Embedders** (OpenAI, Ollama, Google AI, Vertex, Hugging Face, or any OpenAI-compatible endpoint, standalone or linked to a provider) used by **data sources**, and four data-source endpoints: search at `/datasource/{slug}` `[docs]`, plus vector search, metadata query and embedding generation at `/vector`, `/metadata` and `/embeddings` under it `[stack]`. Two options:

1. If the embeddings fed a retrieval pipeline, move the pipeline into a **data source** (Pinecone, PGVector, Chroma, Redis, Qdrant or Weaviate) and query `/datasource/{slug}` with `{"query": "...", "n": 5}`.
2. If you need raw vectors from an application, call the vendor-native passthrough `/llm/call/{slug}/v1/embeddings` against an OpenAI-compatible provider. The OpenAI SDK works unchanged with `base_url=".../llm/call/{slug}/v1"`; it returned 384-dimension vectors from the workshop's mock on both gateways. Grants and the App key apply as on every other path. `[stack]` The data source's own `/embeddings` endpoint is the alternative when a data source exists.

---

## 7. Client code changes

### 7.1 Header mapping

| Portkey header or SDK option | Tyk AI Studio |
|---|---|
| `x-portkey-api-key` | `Authorization: Bearer <App secret>` `[docs]` |
| `x-portkey-provider: @slug` or `x-portkey-virtual-key` | The `{slug}/` prefix in `model`, or the base path `/ai/{slug}/v1` `[docs]` |
| `x-portkey-config` | Nothing. The behaviour lives on the provider, router and App |
| `x-portkey-metadata` | Nothing (6.9) |
| `x-portkey-trace-id`, `x-portkey-span-id`, `x-portkey-parent-span-id` | W3C `traceparent` `[docs]` |
| `x-portkey-cache-force-refresh` | `X-Cache: bypass` (Advanced LLM Cache) `[docs]` |
| `x-portkey-request-timeout` | Nothing per request; per-attempt timeout on the provider |
| `x-portkey-custom-host`, `x-portkey-forward-headers` | Nothing; separate providers per host |
| `x-portkey-strict-open-ai-compliance` | Nothing; use `/llm/call/{slug}/...` for vendor-native bodies `[docs]` |
| `x-portkey-azure-*`, `x-portkey-vertex-*`, `x-portkey-aws-*` | Provider configuration, never per request |
| `anthropic-version` on `/v1/messages` | Still required on `/llm/call/{slug}/v1/messages`; the gateway passes it through `[stack]` |

### 7.2 OpenAI SDK (Python)

Before:

```python
from openai import OpenAI
from portkey_ai import PORTKEY_GATEWAY_URL, createHeaders

client = OpenAI(
    api_key="not-used",
    base_url=PORTKEY_GATEWAY_URL,
    default_headers=createHeaders(api_key=os.environ["PORTKEY_API_KEY"], config="pc-compass-prod",
                                  metadata={"_user": user_id, "team": "contact-centre"}),
)
resp = client.chat.completions.create(model="@anthropic-prod/claude-sonnet-5-5", messages=msgs)
```

After:

```python
from openai import OpenAI

client = OpenAI(api_key=os.environ["TYK_APP_SECRET"], base_url="https://ai-gw.larkspur.example/v1")
resp = client.chat.completions.create(model="anthropic-prod/claude-sonnet-5-5", messages=msgs)
# or, once the router exists:  model="compass/compass-chat"
```

Pinned to one provider, so model names stay bare: `base_url="https://ai-gw.larkspur.example/ai/anthropic-prod/v1"`. `[docs]` `[stack]`

### 7.3 Node, LangChain, Vercel AI SDK

Every OpenAI-compatible client follows the same two-line change: `baseURL` to `https://<edge>/v1`, `apiKey` to the App secret, model prefixed with the provider slug. `[docs]` `[stack]`

```ts
import OpenAI from "openai";
const client = new OpenAI({ apiKey: process.env.TYK_APP_SECRET, baseURL: "https://ai-gw.larkspur.example/v1" });
```

```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="anthropic-prod/claude-sonnet-5-5", api_key=os.environ["TYK_APP_SECRET"], base_url="https://ai-gw.larkspur.example/v1")
```

```ts
import { createOpenAI } from "@ai-sdk/openai";
const tyk = createOpenAI({ apiKey: process.env.TYK_APP_SECRET, baseURL: "https://ai-gw.larkspur.example/v1" });
const model = tyk.chat("anthropic-prod/claude-sonnet-5-5");
```

### 7.4 Anthropic SDK and Claude Code

Portkey's `/v1/messages` accepted Anthropic-format requests for any provider (with unsupported parameters silently dropped). Tyk offers the Messages API in two places: `[docs]`

- **Direct Anthropic providers:** the vendor-native passthrough. The gateway forwards the body untouched and injects the vendor key, so every Anthropic-only parameter (extended thinking, `cache_control`, tool use) works. `[stack]`

  ```python
  from anthropic import Anthropic
  client = Anthropic(api_key=os.environ["TYK_APP_SECRET"], base_url="https://ai-gw.larkspur.example/llm/call/anthropic-prod")
  ```

  The SDK appends `/v1/messages` and sends `anthropic-version` itself. On 2.2.2 both `messages.create` and `messages.count_tokens` worked through this base URL, and the response was Anthropic's own body (including `cache_creation` usage fields), which is the point of the passthrough. `[stack]`

- **Bedrock providers:** `/anthropic/{slug}/v1/messages`. A non-Bedrock provider returns `400`; the model in the body has no effect and the provider's default model is always used. This is the documented path for **Claude Code** (`ANTHROPIC_API_KEY` works in place of `ANTHROPIC_AUTH_TOKEN`): `[docs]`

  ```bash
  export ANTHROPIC_BASE_URL=https://ai-gw.larkspur.example/anthropic/bedrock-eu
  export ANTHROPIC_AUTH_TOKEN=$TYK_APP_SECRET
  export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
  ```

  Claude Code against a *direct* Anthropic provider through `/llm/call/{slug}` is not documented `[unconfirmed]`; the Messages and `count_tokens` calls it depends on do pass through `[stack]`, so it is worth a try before falling back to Bedrock.

Failover does **not** apply on vendor-native or Anthropic Messages paths, only on the OpenAI-compatible ones and Model Routers. If you need failover for Claude, call it through the Main Ingress. `[docs]`

### 7.5 Behaviour differences to test for

| Situation | Portkey | Tyk AI Studio |
|---|---|---|
| Budget exhausted | Key or provider status `exhausted`; request refused | `403`, OpenAI error code `budget_exceeded` `[docs]` `[stack]` |
| Credential awaiting approval | n/a | `401` until an administrator activates it `[docs]` |
| Model not granted | n/a (allow-list error) | `403`, `vendor '<slug>' not found or not supported by your access rights` `[docs]` `[stack]` |
| Router model string sent to the embedded gateway | n/a | The same `403`; routers run on the edge only `[stack]` |
| Guardrail denied | `446` | Generic `403` "blocked by policy" for tools `[docs]`; `400 invalid_request_error` naming the filter for LLM requests `[stack]` |
| Guardrail failed, not denied | `246` with normal body | Normal `200`; event logged `[docs]` |
| Upstream failure after fallbacks | Last upstream status | `502` or `504` since 2.2.0 `[docs]` |
| Who answered | Log only | `X-Tyk-Served-LLM`, `X-Tyk-Served-Model`, `X-Tyk-Failover`, `X-Tyk-Router`, `X-Tyk-Route` `[docs]` `[stack]` |
| Cache hit | Log field | `X-Cache-Status: HIT` `[stack]` |
| Streaming failover | Spans in trace | Only before the first token `[docs]` |

---

## 8. Cutover plan

1. **Build the target in a sandbox first.** Use the official quickstart at `v2.2.2`. Recreate one Portkey Config end to end (Appendix B) and run your integration tests against it before touching production.
2. **Create providers, prices, filters, routers and Teams in production AI Studio.** Publish to catalogs. Push to the edge. Nothing is receiving traffic yet.
3. **Issue Apps.** One per calling service. Hand each team its secret once; the console will not show it again. Have each team confirm `GET /v1/models` lists what they expect.
4. **Run in parallel.** Point a staging deployment or a percentage of traffic at the Tyk edge. Put Semantic Routers in **shadow** mode so decisions are logged but the default route serves. Compare Portkey logs and Tyk analytics for a week: request counts, token counts, cost per model, p95 latency (use `Server-Timing` temporarily), and compliance events versus Portkey guardrail failures. `[docs]` `[stack]`
5. **Flip per App.** Change `base_url` and the key in each service's configuration. Because the model string differs (`@slug/model` becomes `slug/model`), make the model name a configuration value if it was not already.
6. **Watch the first budget period.** Budgets only bite once prices and spend line up; check `Analytics > Budget usage` after the first day and confirm the 80% alert reaches the right people.
7. **Decommission Portkey.** Export logs you must retain (Enterprise, 50,000 rows per job). Delete Configs and API keys. **Rotate every vendor key** that was stored in a Portkey Integration or virtual key: Tyk now holds a fresh key in Secrets, and the old one should stop working everywhere else. `[docs]`
8. **Rollback** is the same two lines in reverse, which is why step 5 is per App.

---

## 9. Gap register

Things Portkey does that Tyk AI Studio 2.2.2 does not, with the best available answer. "Absent" means no such feature is documented; rows are `[docs]` unless noted.

| Portkey capability | Tyk status | Workaround |
|---|---|---|
| Prompt library, versions, labels, partials, `/prompts/*` | Absent | Templates in git, rendered client-side; Asset Catalog for the register (6.8) |
| Per-request metadata, `_user` | Absent on proxy traffic | More Apps; `on_behalf_of` via auth plugins (2.2.1) |
| Feedback API | Absent | Store feedback in your own system keyed by `traceparent` |
| Token-denominated budgets, weekly resets, custom alert thresholds | Monthly currency budgets, 80% and 100% alerts | Convert tokens to currency; `reset-budget` endpoint |
| Rate limits (RPM, TPM) in the core | Plugin or external gateway | Community LLM rate limiting plugin; Tyk API Gateway |
| Same-target retries with `retry-after` | Failover only | Duplicate provider as first fallback `[stack]` |
| Circuit breaker | Absent | None |
| Conditional routing on metadata or URL | Content-based Semantic Router only | Separate Apps or model strings |
| `override_params`, `drop_params` | Absent for proxy traffic | Script filter rewrites, or code |
| Responses API, Realtime, Batches, Files, images, audio, moderations | Not documented in 2.2.2; Responses, Batches, Files listed for 2.3.0 via `/llm/` | Vendor-native passthrough `/llm/call/{slug}/...` `[unconfirmed]` |
| OpenAI-style `/v1/embeddings` proxy | `404` on `/v1` and `/ai` | `/llm/call/{slug}/v1/embeddings` passthrough works with the OpenAI SDK `[stack]`; data sources and Embedders for retrieval |
| Gemini-native endpoint | Not documented (and unconfirmed on Portkey too) | `/llm/call/{slug}` with vendor `google_ai` `[unconfirmed]` |
| Vertex and Hugging Face on the OpenAI-compatible surface | `unsupported_vendor` | `/llm/call/{slug}` only |
| Response redaction | Response filters are block-only | Redact on request |
| Hosted SaaS, free tier with retention | Self-managed is the only documented deployment type | Community edition is free; you run it |
| SCIM | "AI Studio has no SCIM endpoint" | IdP group mapping at login |
| Bulk proxy-log export API | Not documented | Analytics API, direct database access, SIEM via audit JSON lines |
| Agent Gateway (A2A) | Absent | None |

And the reverse, briefly: Tyk brings privacy levels, an approval flow on every credential, OpenAPI tools served over REST and MCP, data sources with six vector stores, a chat UI with tools and RAG for non-developers, edge gateways that survive hub outages, governed metadata, and the full source under AGPL. None of these has a Portkey counterpart.

---

## 10. Post-migration verification checklist

Run each from a client with an App secret, against the **edge** gateway.

- [ ] `GET /v1/models` lists every provider and router the App should have, and nothing else.
- [ ] A chat completion through each provider returns `X-Tyk-Served-LLM` with the expected slug.
- [ ] `"stream": true` streams.
- [ ] A request for an ungranted provider returns `403`.
- [ ] Stop (or mis-key) the primary provider: the response carries `X-Tyk-Failover: true` and the expected fallback; restore it.
- [ ] Router model strings return `X-Tyk-Router` and the weights look right over 20 requests.
- [ ] Semantic router test prompts land on the intended routes in the console's **Test** panel; shadow mode records the same.
- [ ] A prompt containing a test card number is blocked; a prompt with a phone number arrives at the vendor redacted (check the vendor's view in a mock first); both appear under **Compliance overview**.
- [ ] Set an App budget to `0`: `403 budget_exceeded`. Set it back to `null`.
- [ ] `Analytics` shows non-zero cost for each model used. If it shows zero, a model price is missing.
- [ ] `/metrics` answers with the token and `gen_ai_*` series are present.
- [ ] A span per request arrives at your collector with `traceparent` continuity from the calling service.
- [ ] A configuration change in the hub appears in **Audit trail** with a diff, and (if configured) a signed webhook delivery.
- [ ] Log in as a member of a different Team: they cannot see this Team's providers in the Portal.
- [ ] The edge keeps answering while the hub container is stopped for a minute; analytics catch up when it returns. `[docs]`
- [ ] Every vendor key that lived in Portkey has been rotated.

---

## Appendix A: Sources

All retrieved 23 October 2026.

**Tyk AI Studio**

- Overview and edition table: https://tyk.io/docs/ai-management/ai-studio/overview
- Release notes 2.2.0 and 2.2.1: https://tyk.io/docs/developer-support/release-notes/ai-studio
- 2.2.2 changelog (security release): https://github.com/TykTechnologies/ai-studio/blob/main/CHANGELOG-v2.2.2.md
- 2.3.0 working changelog (unreleased): https://github.com/TykTechnologies/ai-studio/blob/main/CHANGELOG-v2.3.0.md
- Docker Hub tags: https://hub.docker.com/r/tykio/tyk-ai-studio/tags and https://hub.docker.com/r/tykio/tyk-ai-studio-ent/tags
- Gateway endpoints and SDK configuration: https://tyk.io/docs/ai-management/ai-studio/proxy
- Architecture, embedded versus edge: https://tyk.io/docs/ai-management/ai-studio/architecture
- LLM providers and failover: https://tyk.io/docs/ai-management/ai-studio/llm-management
- Privacy levels: https://tyk.io/docs/ai-management/ai-studio/privacy-levels
- Apps and the AI Portal: https://tyk.io/docs/ai-management/ai-studio/ai-portal-app
- Teams, catalogs, RBAC: https://tyk.io/docs/ai-management/ai-studio/teams, `/catalogs`, `/rbac`
- Budgets: https://tyk.io/docs/ai-management/ai-studio/budgeting
- Filters, guardrails, compliance events: https://tyk.io/docs/ai-management/ai-studio/filters, `/guardrails`, `/compliance-events`
- Model router and semantic router: https://tyk.io/docs/ai-management/ai-studio/model-router, `/semantic-router`
- Semantic caching: https://tyk.io/docs/ai-management/ai-studio/semantic-caching
- Observability and analytics: https://tyk.io/docs/ai-management/ai-studio/observability, `/analytics`
- Audit trail, webhooks, governed metadata: https://tyk.io/docs/ai-management/ai-studio/audit-trail, `/webhooks`, `/governed-metadata`
- Secrets: https://tyk.io/docs/ai-management/ai-studio/secrets
- Tools, data sources, embedders: https://tyk.io/docs/ai-management/ai-studio/tools, `/datasources-rag`, `/embedders`
- Tyk Dashboard MCP integration and MCP Gateway: https://tyk.io/docs/ai-management/ai-studio/tyk-mcp-integration, https://tyk.io/docs/ai-management/mcp-gateway/overview
- Asset Catalog plugin: https://tyk.io/docs/ai-management/ai-studio/asset-catalog
- Environment variables: https://tyk.io/docs/ai-management/ai-studio/ai-studio-env
- Management API (OpenAPI): https://tyk.io/docs/ai-management/ai-studio/ai-studio-swagger
- Spend caps for agents (budget is the only cap): https://tyk.io/docs/ai-management/agents/track-and-cap-agent-token-spend
- Source and licence (AGPL-3.0): https://github.com/TykTechnologies/ai-studio
- Edge analytics settings (`ANALYTICS_STORE_REQUESTS`, `ANALYTICS_RETENTION_DAYS`): the `microgateway` configuration documents in the same repository
- Community plugins (LLM Response Cache, LLM rate limiting, LLM Price Sync): https://github.com/TykTechnologies/tyk-ai-studio-plugins-ce

**Portkey**

- Acquisition: https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents
- Production gateway open-sourced as gateway 2.0.0 (March 2026): https://github.com/Portkey-AI/gateway/discussions/1576
- Pricing and plans: https://portkey.ai/pricing
- Headers: https://portkey.ai/docs/api-reference/inference-api/headers
- Config object: https://portkey.ai/docs/api-reference/config-object
- Model Catalog and the virtual-key migration: https://portkey.ai/docs/product/model-catalog, https://portkey.ai/docs/support/upgrade-to-model-catalog
- Retries, caching, conditional routing: https://portkey.ai/docs/product/ai-gateway/automatic-retries, `/cache-simple-and-semantic`, `/conditional-routing`
- Guardrails and the check list: https://portkey.ai/docs/product/guardrails, `/guardrails/list-of-guardrail-checks`
- Prompt studio, versioning, partials: https://portkey.ai/docs/product/prompt-engineering-studio
- Observability, traces, metadata, feedback, log export, OpenTelemetry: https://portkey.ai/docs/product/observability and sub-pages
- Access control, workspaces, SSO, SCIM, audit logs: https://portkey.ai/docs/product/enterprise-offering/access-control-management and sub-pages
- Usage-limit policies: https://portkey.ai/docs/api-reference/admin-api/control-plane/policies/usage-limits/create-usage-limits-policy (limit minimums are on https://portkey.ai/docs/product/model-catalog/integrations)
- Messages API and Responses API: https://portkey.ai/docs/product/ai-gateway/messages-api, `/responses-api`
- MCP Gateway: https://portkey.ai/docs/product/mcp-gateway
- Admin API index: https://portkey.ai/docs/_llms/latest/admin-apis.txt

---

## Appendix B: Worked example, Larkspur Bank's Compass assistant

Larkspur Bank (a fictional bank) runs its contact-centre assistant, Compass, through Portkey. This is its estate and what it becomes.

**Portkey estate**

- Workspace `contact-centre`; service key `compass-backend-prod` with default Config `pc-compass-prod` and metadata `team=contact-centre`, `env=prod`.
- AI Providers `@anthropic-prod` (allowed `claude-*`), `@openai-prod`, `@bedrock-eu`.
- Config `pc-compass-prod`: the JSON in 6.4 (weighted split Anthropic 70 / OpenAI-then-Bedrock 30, retry on 429 and 503, simple cache one hour, 30 s timeout, PII input guardrail with deny, "no financial promises" output guardrail with deny).
- Prompt `compass-system@production` with partial `larkspur-tone`.
- Usage-limit policy: $500 per month on the key, alert at 80%.
- Rate limit: 600 requests per minute on `@anthropic-prod`.

**Tyk AI Studio estate (Enterprise, v2.2.2)**

| Portkey object | Tyk object | Where |
|---|---|---|
| Vendor keys | Secrets `ANTHROPIC_KEY`, `OPENAI_KEY`, `BEDROCK_ACCESS_KEY`, `BEDROCK_SECRET_KEY` | `Settings > Secrets` |
| `@anthropic-prod` | Provider `Anthropic Prod`, vendor `anthropic`, allowed `^claude-.*$`, privacy 75, **failover**: OpenAI Prod / `gpt-5`, then Bedrock EU / `anthropic.claude-sonnet-5-5-v1:0`; triggers 429, 500, 502, 503, timeout 30 s | `LLM management > LLM providers` |
| `@openai-prod`, `@bedrock-eu` | Providers `OpenAI Prod`, `Bedrock EU`, privacy 75 | same |
| `loadbalance` 70/30 | Model Router `compass`, pool `compass-*`, weighted: Anthropic Prod weight 7 → `claude-sonnet-5-5`, OpenAI Prod weight 3 → `gpt-5` | `LLM management > Model Routers` |
| `retry` | Covered by the failover triggers; for a same-vendor retry, a second provider `Anthropic Prod (retry)` on the same secret as first fallback | provider |
| `cache: simple, 3600` | LLM Response Cache plugin on Anthropic Prod and OpenAI Prod, TTL 3600 | `Plugins > Marketplace` |
| `gr-pii-check` (deny) | Guardrail `Personal data (block)`: built-in `pii`, action Block, request direction; plus a Tengo script filter for card numbers and SSNs (the skeleton in 6.6) | `Context management > Filters`, attached to all three providers |
| `gr-no-promises` (deny) | Script response filter blocking promised outcomes, attached to the providers and the Compass chat | same |
| Workspace `contact-centre` | Team `Contact Centre`; LLM catalog `Contact centre models` containing the three providers and the router | `Access > Teams`, `Catalogs` |
| Key `compass-backend-prod` | App `Compass Backend`, grants: the three providers and the router; monthly budget 500 USD | AI Portal, activated by an administrator |
| Policy $500, alert 80% | The App budget above (alerts at 80% and 100% are built in) | App |
| 600 RPM on Anthropic | LLM rate limiting plugin on Anthropic Prod, or a Tyk API Gateway in front | marketplace |
| `compass-system@production`, partial | `prompts/compass-system.mustache` and `prompts/_larkspur-tone.mustache` in the Compass repository, rendered at startup; registered in the Asset Catalog as a Prompt asset owned by the platform lead | git |
| Metadata `team`, `env` | Separate Apps `Compass Backend` and `Compass Backend (staging)`; the Team gives the `team` dimension in Analytics | Apps |

**Compass code change**

```python
# before
client = OpenAI(base_url=PORTKEY_GATEWAY_URL, api_key="x",
                default_headers=createHeaders(api_key=PORTKEY_KEY, config="pc-compass-prod", metadata={"_user": agent_id}))
system = portkey.prompts.render(prompt_id="compass-system@production", variables={"agent": agent_name})
resp = client.chat.completions.create(model="@anthropic-prod/claude-sonnet-5-5", messages=[*system, *history])

# after
client = OpenAI(base_url="https://ai-gw.larkspur.example/v1", api_key=TYK_APP_SECRET)
system = chevron.render(open("prompts/compass-system.mustache").read(), {"agent": agent_name}, partials_path="prompts")
resp = client.chat.completions.create(model="compass/compass-chat", messages=[{"role": "system", "content": system}, *history])
```

The provider choice, the fallback chain, the cache, the PII rule and the budget are now the platform team's configuration rather than the application's Config, which is the point of the migration.

---

## Appendix C: Live verification log, v2.2.2 Enterprise, 23 October 2026

Run against a workshop stack (hub, edge gateway, mock OpenAI-compatible LLM, Qdrant, and a real Anthropic provider) on `v2.2.2` Enterprise. Throwaway objects (two mock-backed providers, one App, one Model Router) were created through the management API and deleted afterwards. Real Anthropic calls were limited to three requests of eight output tokens.

| Check | Result |
|---|---|
| `GET /common/system` | `edition: enterprise`, `version: 2.2.2` |
| Edge `/api/v1/plugins` and `POST /api/v1/auth/token` | `404` on both (the 2.2.2 hardening) |
| App created by API, credential read before activation | Gateway `401` until `POST .../activate-credential` (`204`) |
| `GET /v1/models` with the App secret | Only granted providers and the router, including `allowed_models` patterns as entries |
| Main Ingress, `migverify-mock/mock-sonnet` | `200`, `X-Tyk-Served-LLM`, `X-Tyk-Served-Model` |
| Ungranted provider `openai/gpt-5` | `403`, `vendor 'openai' not found or not supported by your access rights` |
| `"stream": true` via curl and the OpenAI SDK | SSE chunks (18 for a short reply) |
| Pinned path `/ai/migverify-mock/v1/chat/completions` | `200`, same headers |
| Failover: primary returns `503` | `X-Tyk-Failover: true`, served by the fallback, on embedded and edge |
| `/llm/call/migverify-mock/v1/embeddings` (curl and OpenAI SDK with passthrough base URL) | `200`, 384-dimension vectors, on embedded and edge |
| `/v1/embeddings`, `/ai/{slug}/v1/embeddings` | `404 page not found` |
| Anthropic SDK, `base_url=.../llm/call/anthropic`, `messages.create` and `messages.count_tokens` | `200`, Anthropic-native body |
| `/anthropic/anthropic/v1/messages` (non-Bedrock provider) | `400`, `the Anthropic Messages bridge only supports Bedrock LLMs` |
| Main Ingress to real Anthropic, `anthropic/claude-haiku-5-5` | `200`, OpenAI-shaped body, `X-Tyk-Served-LLM: anthropic` |
| `PATCH /api/v1/apps/{id}` with only `monthly_budget` | `llm_ids` emptied |
| Full-attribute `PATCH` with `monthly_budget: 0`, then a call | `403`, code `budget_exceeded`, `Budget limit exceeded: app monthly budget exceeded (budget is 0)` |
| `POST /api/v1/apps/{id}/reset-budget` with budget `0` or `null` | `400 app does not have a budget configured` |
| Seeded guardrails attached to the provider, prompt with phone and email | Mock echoed `[REDACTED:PHONE_US]` and `[REDACTED:EMAIL]`, on embedded and edge |
| Prompt with an AWS access key and a GitHub token | `400 invalid_request_error`, `Policy error: Credentials in prompts (block) - Request blocked by policy` |
| `GET /api/v1/compliance/events` | Events `guardrail.secrets.aws_access_key`, `guardrail.secrets.github_pat`, `guardrail.pii.email` with filter name and action |
| `POST /api/v1/filters/test` with the workshop's Tengo script as plain text | `success: true`, redaction events; base64 input fails to compile |
| `POST /api/v1/model-routers` with `weight: 0.7` | `400`, `cannot unmarshal number 0.7 ... of type int` |
| Same with integer weights 3 and 1, granted, pushed; six calls to `migverify-router/mv-chat` on the edge | `X-Tyk-Router`, `X-Tyk-Route`, `X-Tyk-Route-Reason: model_pattern`; one of six went to the weight-1 vendor and failed over |
| Same router model string on the embedded gateway | `403` (not routed) |
| `POST /api/v1/edges/reload-all`, then `GET /api/v1/sync/status` | `pending=1` then `synced=1` within seconds |
| Edge response headers | `Server-Timing: gw-pre, upstream-ttfb, upstream, elapsed, conn` present with `GATEWAY_SERVER_TIMING` on |
| `/datasource/{slug}`, `/vector`, `/metadata`, `/embeddings` on the edge with an unknown slug | `403 datasource ... not found` on all four, so the routes exist |
| Edge `/metrics` | `gen_ai_*` histograms plus `aistudio_llm_requests_total`, `aistudio_llm_failover_total`, `aistudio_policy_blocks_total`, `aistudio_compliance_events_total`, `aistudio_guardrail_latency_seconds` |
| `GET /api/v1/analytics/token-usage-and-cost-for-app` | Non-zero cost from the seeded model prices for the App's traffic |
| `GET /api/v1/analytics/proxy-logs-for-app` | Records with `model_name`, `vendor`, `response_code`, `failover_attempt`, `request_body`, `response_body` |
| `GET /api/v1/audit/records?limit=1` | Records with user, IP, auth method, action, method, URL |

Not verified live: Azure OpenAI as a provider, Claude Code through `/llm/call/{slug}`, LLM call settings on proxy traffic, Vertex and Hugging Face, the marketplace cache and rate-limit plugins, SSO, and semantic routers.
