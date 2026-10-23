# Portkey to Tyk AI Studio

A practical migration guide for platform teams moving LLM traffic, governance and observability off Portkey (now Prisma AIRS AI Gateway, after the Palo Alto Networks acquisition) and onto **Tyk AI Studio v2.2.2 Enterprise Edition**.

**Read the guide: [MIGRATION-FROM-PORTKEY.md](MIGRATION-FROM-PORTKEY.md).**

| | |
|---|---|
| Target | Tyk AI Studio v2.2.2 Enterprise (latest stable at time of writing) |
| Written | 23 October 2026 |
| Verified | Docs-tagged claims checked against tyk.io and portkey.ai documentation; stack-tagged claims run live on a v2.2.2 Enterprise installation (see Appendix C of the guide) |

## What is in the guide

1. Why teams are migrating now
2. The mental model: every Portkey concept and its Tyk equivalent
3. Which edition you need (Community versus Enterprise)
4. Inventorying your Portkey estate through the Admin API
5. Standing up Tyk AI Studio v2.2.2
6. Migration step by step: providers and prices, consumers, Gateway Configs, caching, guardrails, budgets and rate limits, prompts, observability, governance, MCP and tools
7. Client code changes for the OpenAI SDK, Node, LangChain, Vercel AI SDK, the Anthropic SDK and Claude Code
8. Cutover plan
9. Gap register: what does not map, with workarounds
10. Post-migration verification checklist

Appendix A lists the sources, Appendix B is a worked example (a fictional bank's assistant moving from one Portkey Config to Tyk objects), and Appendix C is the log of live checks on v2.2.2.

## What else is here

```
MIGRATION-FROM-PORTKEY.md        the guide
scripts/export-portkey.sh        export workspaces, keys, integrations, configs, prompts, guardrails and usage policies through the Portkey Admin API
scripts/translate-config.py      turn one Portkey Config into the Tyk objects it implies (providers, failover, Model Router, cache, filters, and what cannot be translated), optionally as JSON:API payloads
scripts/verify-tyk.sh            post-migration checks against a Tyk edge gateway (models, grants, streaming, failover, router, embeddings, metrics, guardrail block)
examples/                        sample Portkey Configs, Tyk management API payloads and two Tengo filters (see examples/README.md)
docs/positioning.md              the case for Tyk against Portkey, with and without the wider Tyk platform
```

Typical use:

```bash
PORTKEY_ADMIN_KEY=... ./scripts/export-portkey.sh portkey-export
./scripts/translate-config.py portkey-export/configs/<slug>.json --payloads tyk-payloads/
TYK_APP_SECRET=... ./scripts/verify-tyk.sh --gateway https://<edge> --model <slug>/<model> --metrics
```

The scripts need bash 3.2 or later, curl, jq and Python 3.8 or later; nothing is installed.

## How claims are tagged

| Tag | Meaning |
|---|---|
| `[docs]` | Confirmed on official documentation on the date above |
| `[stack]` | Observed on a live v2.2.2 Enterprise installation |
| `[unconfirmed]` | Not found in official documentation; test before relying on it |

Both products move quickly. If you find something that no longer holds, open an issue with the version you tested and what you saw.
