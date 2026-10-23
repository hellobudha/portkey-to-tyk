# Positioning: Tyk against Portkey, with and without the wider platform

A companion to the migration guide for the people who have to argue the case rather than execute it. The guide stays neutral; this page does not. Facts are from the sources listed at the end, checked on 23 October 2026.

## The short version

Bringing the wider Tyk platform (Tyk Gateway and Dashboard, MCP Gateway, Enterprise Developer Portal) into a comparison with Portkey **strengthens** the case for platform and API teams and for the agent story, is **noise** in a developer-led gateway bake-off, and **weakens credibility** if presented as a single unified platform beyond the integration points that exist today.

## What changed on Portkey's side

- Palo Alto Networks closed its acquisition of Portkey on 29 May 2026. Portkey becomes the AI Gateway inside Prisma AIRS, Palo Alto's AI security platform; every docs page now carries the Prisma AIRS banner.
- The product's centre of gravity therefore moves from "LLMOps for developers" to "AI security control plane within a security vendor's portfolio". Nothing has been published about plan continuity or the open-source gateway's roadmap.
- Portkey's own guardrail partner list now includes Prisma AIRS alongside Lakera, Patronus, Aporia, Azure and Bedrock. One of those partners is now the owner.

## Where the wider platform genuinely helps

**It closes AI Studio's visible gaps.** Three rows in the guide's gap register are the ones an AI gateway buyer notices first: no per-request rate limits in the core, no circuit breaker, no same-target retries. Tyk Gateway has rate limits, quotas and circuit breakers, plus a wider authentication menu (mTLS, OAuth 2.0, JWT, API keys). AI Studio alone loses those rows; AI Studio with Tyk Gateway in front wins them, at the honest cost of being two products with two control planes.

**The agent story is where Tyk is ahead, and Portkey competes there too.** Portkey's MCP Gateway entered beta in September 2025 and its Agent Gateway has no stated status or plan. Tyk's MCP Gateway is a feature of the shipping Tyk Gateway (5.13 and later, MCP 2025-11-25, Streamable HTTP): per-tool, per-resource and per-prompt policies and rate limits, discovery filtering so an agent only sees what it may call, OAuth 2.1 Protected Resource Metadata implemented natively, REST-to-MCP generation from Tyk OAS APIs (5.15, Enterprise), MCP-specific access-log fields and OpenTelemetry metrics, and per-primitive analytics in the Dashboard. This is the single strongest reason to widen the frame.

**Productising AI for consumers is a category Portkey does not enter.** Portkey has workspaces and keys. Tyk has the AI Portal inside AI Studio for internal self-service with an approval step on every credential, and the Enterprise Developer Portal for API Products, Subscription Plans, automatic or administrator approval, multiple organisations and teams, catalogs per audience and several Dashboards as providers. For a buyer whose job is to expose AI capabilities to other teams or partners under governed plans, there is no Portkey answer.

**Independence is now a differentiator.** Open source (AI Studio under AGPL-3.0; MCP pass-through proxies on every Tyk Gateway licence), self-managed, pluggable guardrail providers, and no dependency on one security vendor's roadmap. State it factually and let the buyer draw the conclusion.

## Where it is irrelevant or harmful

**Developer-led bake-offs.** A team comparing gateways on prompt management, Config expressiveness, provider breadth, Responses and Realtime coverage, OpenTelemetry ingest and the feedback API will find nothing in Tyk Gateway or the Developer Portal that answers those rows. Mentioning them reads as changing the subject, and it makes the answer sound like "buy three products to match one". Lead with AI Studio alone and the gap register, and win on governance, privacy levels, the portal and failover transparency.

**Claiming a unified platform that is not yet unified.** Today the products meet at defined points: AI Studio connects to a Tyk Dashboard, imports MCP proxies, publishes them in the AI Portal and mints Tyk keys for Apps; Tyk Gateway can sit in front of AI Studio for quotas. They remain separate control planes with separate analytics, and AI Studio chats cannot use the imported MCP servers. A platform buyer will probe that seam in the first demo. Describe the integration points precisely and the story holds; call it one platform and the first question exposes it.

**Licence sprawl.** The full story needs AI Studio Enterprise, Tyk Gateway Enterprise for REST-to-MCP and upstream OAuth, and a Developer Portal licence. Against Portkey's published tiers that is a harder mid-market conversation. It is fine against an enterprise that already runs Tyk; it is a liability against a team that found Portkey on a credit card.

**Security depth.** Do not fight Prisma AIRS on runtime AI security. Tyk's answer is gateway-enforced guardrails with pluggable detectors, privacy levels, compliance events and an audit trail, plus governance of the API side that agents actually touch.

## Frame by buyer

| Buyer | Lead with | Bring in the platform? |
|---|---|---|
| AI engineering team replacing a gateway | AI Studio versus Portkey, feature for feature, gaps included | No. Mention Tyk Gateway only as the answer to the rate-limit and circuit-breaker rows |
| Platform or API team that already runs Tyk | The whole loop: model calls (AI Studio), tools (MCP Gateway), the APIs behind the tools (Tyk Gateway), who may consume all of it (both portals) | Yes. It is the whole argument, and they can verify it in their own environment |
| Security-led buyer | Gateway-enforced guardrails, privacy levels, audit trail, compliance events, pluggable detectors | Partly. Independence and the API side, not security depth |

The sentence that carries the strong version: **Portkey governs the model call; Tyk governs the whole agent loop, from the model to the tools to the APIs behind them, and who may consume each.** Everything in it is documented today. The parts that are not yet joined up (shared analytics, chat access to imported MCP servers) stay out of it.

## Caveats

- Portkey's MCP maturity is read from its documentation and changelog, not from use.
- Tyk Cloud hosts the API management platform, not AI Studio, which the docs list as self-managed only. "Hosted" is not a line Tyk can use against Portkey's SaaS.
- Versions move: this page is accurate for Tyk AI Studio 2.2.2, Tyk Gateway 5.15 and the Portkey docs as of the date above.

## Sources

- Palo Alto Networks completes acquisition of Portkey: https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents
- Portkey MCP Gateway: https://portkey.ai/docs/product/mcp-gateway ; Agent Gateway: https://portkey.ai/docs/product/agent-gateway ; guardrail partners: https://portkey.ai/docs/product/guardrails/list-of-guardrail-checks ; pricing: https://portkey.ai/pricing
- Tyk MCP Gateway overview: https://tyk.io/docs/ai-management/mcp-gateway/overview
- Tyk AI management overview (AI Studio and MCP Gateway "cover AI traffic in both directions"): https://tyk.io/docs/ai-management/overview
- Tyk Dashboard MCP integration (import, publish, key minting; chats cannot use imported servers): https://tyk.io/docs/ai-management/ai-studio/tyk-mcp-integration
- Tyk Enterprise Developer Portal overview: https://tyk.io/docs/portal/overview
- AI Studio edition table and licence: https://tyk.io/docs/ai-management/ai-studio/overview ; source and AGPL-3.0 licence: https://github.com/TykTechnologies/ai-studio
- Spend caps for agents (budget is the only cap in AI Studio core): https://tyk.io/docs/ai-management/agents/track-and-cap-agent-token-spend
