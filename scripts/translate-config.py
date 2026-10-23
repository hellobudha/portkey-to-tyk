#!/usr/bin/env python3
"""Translate a Portkey Gateway Config into the Tyk AI Studio objects it implies.

    ./scripts/translate-config.py CONFIG.json [--name NAME] [--slug-map MAP.json]
                                  [--json] [--payloads DIR]

Reads one Portkey Config (the JSON body from GET /v1/configs/{slug}, or an inline config)
and prints a migration plan: the LLM providers to create, the failover chain, a Model Router
pool for load balancing, cache and filter notes, and everything that has no Tyk equivalent.
With --payloads DIR it also writes JSON:API request bodies for the management API.

Only the standard library is used. Behaviour follows the migration guide (section 8):
  fallback      -> Failover list on the primary provider
  loadbalance   -> Model Router pool, weighted, integer weights
  conditional   -> manual (Semantic Router or separate Apps); each branch is still translated
  retry         -> failover triggers (no same-target retries in Tyk)
  request_timeout -> per-attempt timeout
  cache         -> LLM Response Cache (simple) or Advanced LLM Cache (semantic) plugin
  guardrails    -> filters (Block when deny, else Log)
  cb_config, metadata/url conditions, drop/override/default params, forward_headers -> flagged
"""
import argparse
import json
import math
import os
import re
import sys
from functools import reduce

ALLOWED_TRIGGER_CODES = {408, 429}
DEFAULT_TRIGGERS = [408, 429, 500, 502, 503, 504]
VENDOR_HINTS = [
    ("anthropic", "anthropic"), ("claude", "anthropic"), ("bedrock", "bedrock"), ("vertex", "vertex"),
    ("gemini", "google_ai"), ("google", "google_ai"), ("ollama", "ollama"), ("huggingface", "huggingface"),
    ("hf-", "huggingface"), ("azure", "openai"), ("openai", "openai"),
]
OPENAI_COMPATIBLE = ["groq", "mistral", "together", "openrouter", "deepseek", "fireworks", "perplexity", "vllm", "cerebras", "xai"]


class Plan:
    def __init__(self, name):
        self.name = name
        self.providers = {}      # tyk slug -> dict
        self.failover = {}       # primary tyk slug -> {"targets": [...], "triggers": {...}}
        self.router = None
        self.conditional = []
        self.cache = None
        self.filters = []
        self.notes = []          # (severity, text)
        self.manual = []         # untranslatable items

    def note(self, text, severity="note"):
        self.notes.append((severity, text))

    def provider(self, ref, model=None, custom_host=None):
        slug = ref["tyk_slug"]
        p = self.providers.setdefault(slug, {
            "portkey_ref": ref["portkey_ref"], "tyk_slug": slug, "vendor": ref["vendor"],
            "vendor_note": ref["vendor_note"], "models": [], "custom_host": None,
        })
        if model and model not in p["models"]:
            p["models"].append(model)
        if custom_host:
            p["custom_host"] = custom_host
        return p


def resolve_ref(node, slug_map):
    """Turn a target's provider/virtual_key fields into a provider reference."""
    raw = node.get("provider") or node.get("virtual_key") or node.get("virtualKey")
    if not raw:
        return None
    raw = str(raw)
    is_slug = raw.startswith("@") or ("virtual_key" in node or "virtualKey" in node)
    slug = raw.lstrip("@")
    tyk_slug = slug_map.get(raw) or slug_map.get(slug) or re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
    lowered = slug.lower()
    vendor, vendor_note = None, ""
    for hint, v in VENDOR_HINTS:
        if hint in lowered:
            vendor = v
            break
    if vendor is None:
        for name in OPENAI_COMPATIBLE:
            if name in lowered:
                vendor, vendor_note = "openai", "OpenAI-compatible upstream: vendor openai with a custom API Endpoint"
                break
    if vendor is None:
        vendor, vendor_note = "openai", "vendor guessed; confirm and set the API Endpoint"
    if "azure" in lowered:
        vendor_note = "Azure OpenAI is not a documented vendor; try openai with the deployment URL [unconfirmed]"
    if "vertex" in lowered or "huggingface" in lowered or "hf-" in lowered:
        vendor_note = "not served on /v1 or /ai (unsupported_vendor); only via /llm/call/{slug}"
    return {"portkey_ref": raw if is_slug or raw.startswith("@") else f"{raw} (bare provider, no slug)",
            "tyk_slug": tyk_slug, "vendor": vendor, "vendor_note": vendor_note}


def model_of(node):
    op = node.get("override_params") or node.get("overrideParams") or {}
    return op.get("model")


def mode_of(node):
    strategy = node.get("strategy") or {}
    mode = strategy.get("mode")
    if not mode and node.get("targets"):
        mode = "single"
    return mode


def integer_weights(weights):
    """Scale fractional weights to the smallest integer ratio (0.7/0.3 -> 7/3)."""
    scale = 1
    for _ in range(7):
        if all(abs(w * scale - round(w * scale)) < 1e-9 for w in weights):
            break
        scale *= 10
    ints = [max(1, int(round(w * scale))) for w in weights]
    g = reduce(math.gcd, ints)
    return [i // g for i in ints]


def leaves_in_order(node, slug_map, plan, path):
    """Flatten a target subtree into an ordered list of (ref, model, custom_host) leaves."""
    mode = mode_of(node)
    if not node.get("targets"):
        ref = resolve_ref(node, slug_map)
        if ref is None:
            plan.note(f"{path}: target has no provider or virtual_key; skipped", "warn")
            return []
        return [(ref, model_of(node), node.get("custom_host"))]
    out = []
    if mode == "loadbalance":
        plan.note(f"{path}: a weighted group sits inside a fallback chain. Tyk failover targets are single "
                  f"provider/model pairs, so its vendors are listed as successive fallbacks in order", "warn")
    if mode == "conditional":
        plan.note(f"{path}: conditional routing nested inside another strategy; translated branch by branch", "warn")
    for i, child in enumerate(node.get("targets", [])):
        out.extend(leaves_in_order(child, slug_map, plan, f"{path}.targets[{i}]"))
    return out


def triggers_from(cfg, plan, top):
    retry = top.get("retry") or cfg.get("retry") or {}
    retry_codes = retry.get("on_status_codes") or retry.get("onStatusCodes")
    fallback_codes = (top.get("strategy") or {}).get("on_status_codes")
    # the fallback strategy's own codes describe when Portkey moved to the next target, which is what a
    # Tyk failover trigger means; retry codes are the next best signal, then Tyk's defaults
    chosen = fallback_codes or retry_codes or DEFAULT_TRIGGERS
    kept, dropped = [], []
    for c in chosen:
        try:
            c = int(c)
        except (TypeError, ValueError):
            continue
        (kept if (500 <= c <= 599 or c in ALLOWED_TRIGGER_CODES) else dropped).append(c)
    if dropped:
        plan.note(f"retry/fallback status codes {dropped} cannot be failover triggers (only 5xx, 408 and 429 are allowed); dropped", "warn")
    if retry.get("attempts", 0) and retry.get("attempts", 0) > 1:
        plan.manual.append(f"retry.attempts={retry['attempts']}: Tyk does not retry the same target. To emulate one retry, add a second provider on the same vendor key as the first fallback.")
    if retry.get("use_retry_after_headers") or retry.get("use_retry_after_header"):
        plan.manual.append("retry.use_retry_after_headers: no equivalent; failover moves on immediately.")
    timeout_ms = top.get("request_timeout") or cfg.get("request_timeout")
    triggers = {"status_codes": sorted(set(kept)), "on_timeout": True, "on_connection_error": True}
    if timeout_ms:
        try:
            triggers["timeout_seconds"] = max(1, int(math.ceil(float(timeout_ms) / 1000.0)))
        except (TypeError, ValueError):
            pass
    return triggers


def translate_top(node, cfg, plan, slug_map, label="config"):
    mode = mode_of(node)
    if mode == "fallback":
        leaves = leaves_in_order(node, slug_map, plan, label)
        if not leaves:
            return
        primary_ref, primary_model, host = leaves[0]
        p = plan.provider(primary_ref, primary_model, host)
        targets = []
        for ref, model, h in leaves[1:]:
            plan.provider(ref, model, h)
            targets.append({"tyk_slug": ref["tyk_slug"], "model": model or "<provider default model>"})
        if len(targets) > 10:
            plan.note(f"{label}: {len(targets)} fallbacks; Tyk allows at most 10 per provider", "warn")
        plan.failover[p["tyk_slug"]] = {"targets": targets[:10], "triggers": triggers_from(cfg, plan, node)}
        plan.note(f"{label}: failover is a property of the provider '{p['tyk_slug']}', so every App calling it inherits this chain")
    elif mode == "loadbalance":
        vendors = []
        weights = []
        for i, child in enumerate(node.get("targets", [])):
            leaves = leaves_in_order(child, slug_map, plan, f"{label}.targets[{i}]")
            if not leaves:
                continue
            ref, model, host = leaves[0]
            p = plan.provider(ref, model, host)
            vendors.append({"tyk_slug": p["tyk_slug"], "model": model or "<provider default model>"})
            weights.append(float(child.get("weight", 1) or 1))
            if len(leaves) > 1:
                rest = [{"tyk_slug": r["tyk_slug"], "model": m or "<provider default model>"} for r, m, _ in leaves[1:]]
                for r, m, h in leaves[1:]:
                    plan.provider(r, m, h)
                plan.failover[p["tyk_slug"]] = {"targets": rest[:10], "triggers": triggers_from(cfg, plan, child)}
        if vendors:
            ints = integer_weights(weights) if weights else []
            for v, w in zip(vendors, ints):
                v["weight"] = w
            source_model = vendors[0]["model"] if vendors else "<model>"
            plan.router = {"slug": re.sub(r"[^a-z0-9]+", "-", plan.name.lower()).strip("-") or "router",
                           "pool": "default", "model_pattern": f"{plan.name.lower().split()[0]}-*",
                           "source_model": f"{plan.name.lower().split()[0]}-chat", "algorithm": "weighted",
                           "vendors": vendors}
            plan.note("loadbalance: Model Routers are Enterprise and run on edge gateways only; weights must be integers")
            if cfg.get("retry") or node.get("retry"):
                plan.note("retry on a load-balanced config: a Model Router does not retry; each vendor's provider needs its own failover list if you want that")
    elif mode == "conditional":
        strategy = node.get("strategy") or {}
        for i, cond in enumerate(strategy.get("conditions", [])):
            plan.conditional.append({"query": cond.get("query"), "then": cond.get("then")})
        if strategy.get("default"):
            plan.conditional.append({"query": "default", "then": strategy.get("default")})
        for i, child in enumerate(node.get("targets", [])):
            name = child.get("name") or f"targets[{i}]"
            translate_top(child, cfg, plan, slug_map, f"{label}.{name}")
        plan.manual.append("conditional strategy: Tyk has no routing on request metadata or URL. Content-based conditions become a Semantic Router (Enterprise, edge only); caller-based conditions become separate Apps or model strings chosen in code.")
    else:  # single or a bare provider
        leaves = leaves_in_order(node, slug_map, plan, label)
        for ref, model, host in leaves:
            plan.provider(ref, model, host)


def translate(cfg, name, slug_map):
    plan = Plan(name)
    translate_top(cfg, cfg, plan, slug_map)

    cache = cfg.get("cache")
    if cache:
        mode = cache.get("mode", "simple")
        plan.cache = {"mode": mode, "max_age": cache.get("max_age"),
                      "plugin": "Advanced LLM Cache (Enterprise)" if mode == "semantic" else "LLM Response Cache (Community marketplace)"}

    for key, direction in (("input_guardrails", "request"), ("output_guardrails", "response"),
                           ("before_request_hooks", "request"), ("after_request_hooks", "response")):
        for item in cfg.get(key, []) or []:
            if isinstance(item, str):
                gid, deny, is_async = item, False, True
            else:
                gid, deny, is_async = item.get("id", "<inline checks>"), bool(item.get("deny")), item.get("async", True)
            action = "Block" if deny else "Log"
            note = ""
            if direction == "response" and deny:
                note = "response filters are block-only"
            if is_async and deny:
                note = (note + "; " if note else "") + "Portkey async+deny could not block; Tyk runs filters inline, so this will now block"
            plan.filters.append({"portkey_id": gid, "direction": direction, "action": action, "note": note})

    if cfg.get("cb_config"):
        plan.manual.append("cb_config: no circuit breaker in Tyk AI Studio; a failing primary is failed over on every request.")
    for key in ("default_params", "drop_params"):
        if cfg.get(key):
            plan.manual.append(f"{key}: not applied by the gateway; move to application code or a script filter that rewrites the request.")
    extra_overrides = {k: v for k, v in (cfg.get("override_params") or {}).items() if k != "model"}
    if extra_overrides:
        plan.manual.append(f"override_params other than model ({', '.join(extra_overrides)}): not applied by the gateway; application code or a script filter.")
    if cfg.get("forward_headers"):
        plan.manual.append("forward_headers: no equivalent; an upstream that needs extra headers needs a plugin [unconfirmed].")
    if cfg.get("strict_open_ai_compliance") is False:
        plan.manual.append("strict_open_ai_compliance=false: use the vendor-native passthrough /llm/call/{slug}/... for vendor-only fields.")
    if cfg.get("prompt_id"):
        plan.manual.append(f"prompt_id={cfg['prompt_id']}: Tyk has no prompt library; render the template client-side (guide section 10).")
    for p in plan.providers.values():
        if p["custom_host"]:
            plan.note(f"{p['tyk_slug']}: custom_host {p['custom_host']} becomes this provider's API Endpoint (one provider per host)")
    return plan


def render_markdown(plan):
    out = [f"# Tyk AI Studio plan for Portkey config `{plan.name}`", ""]
    out.append("## Providers to create (`POST /api/v1/llms`)")
    out.append("")
    out.append("| Portkey reference | Tyk provider slug | Vendor | Models seen | Endpoint | Secret |")
    out.append("|---|---|---|---|---|---|")
    for p in plan.providers.values():
        models = ", ".join(m for m in p["models"] if m) or "(provider default)"
        endpoint = p["custom_host"] or "vendor default"
        vendor = p["vendor"] + (f" ({p['vendor_note']})" if p["vendor_note"] else "")
        out.append(f"| `{p['portkey_ref']}` | `{p['tyk_slug']}` | {vendor} | {models} | {endpoint} | `$SECRET/{p['tyk_slug'].upper().replace('-', '_')}_KEY` |")
    out.append("")
    out.append("Set `allowed_models` to the models seen (as regexes) and a privacy level before granting anything.")
    out.append("")
    if plan.failover:
        out.append("## Failover (on the primary provider)")
        out.append("")
        for primary, fo in plan.failover.items():
            chain = " -> ".join(f"`{t['tyk_slug']}` / `{t['model']}`" for t in fo["targets"]) or "(none)"
            out.append(f"- **`{primary}`**: {chain}")
            trig = fo["triggers"]
            tmo = f", per-attempt timeout {trig['timeout_seconds']} s" if "timeout_seconds" in trig else ""
            out.append(f"  - triggers: status codes {trig['status_codes']}, timeout, connection error{tmo}")
        out.append("")
    if plan.router:
        r = plan.router
        out.append("## Model Router (Enterprise, edge gateways only)")
        out.append("")
        out.append(f"- slug `{r['slug']}`, pool `{r['pool']}`, pattern `{r['model_pattern']}`, algorithm `{r['algorithm']}`")
        out.append(f"- applications call `{r['slug']}/{r['source_model']}`")
        out.append("")
        out.append("| Vendor (Tyk provider) | Weight | Maps to model |")
        out.append("|---|---|---|")
        for v in r["vendors"]:
            out.append(f"| `{v['tyk_slug']}` | {v['weight']} | `{v['model']}` |")
        out.append("")
    if plan.conditional:
        out.append("## Conditional routing (manual)")
        out.append("")
        for c in plan.conditional:
            out.append(f"- when `{json.dumps(c['query'])}` -> target `{c['then']}`")
        out.append("")
    if plan.cache:
        c = plan.cache
        out.append("## Caching")
        out.append("")
        out.append(f"- `{c['mode']}` cache, max_age {c['max_age']} -> **{c['plugin']}** attached to each provider; TTL is a plugin setting")
        out.append("")
    if plan.filters:
        out.append("## Guardrails -> filters")
        out.append("")
        out.append("| Portkey guardrail | Direction | Tyk action | Note |")
        out.append("|---|---|---|---|")
        for f in plan.filters:
            out.append(f"| `{f['portkey_id']}` | {f['direction']} | {f['action']} | {f['note']} |")
        out.append("")
        out.append("Recreate each check as a guardrail (built-in detector or external provider) or a Tengo script filter, then attach to the providers above. Filters execute in Enterprise only.")
        out.append("")
    if plan.manual:
        out.append("## Not translatable automatically")
        out.append("")
        for m in plan.manual:
            out.append(f"- {m}")
        out.append("")
    if plan.notes:
        out.append("## Notes")
        out.append("")
        for sev, text in plan.notes:
            out.append(f"- {'WARNING: ' if sev == 'warn' else ''}{text}")
        out.append("")
    return "\n".join(out)


def jsonapi(type_, attrs):
    return {"data": {"type": type_, "attributes": attrs}}


def write_payloads(plan, directory):
    os.makedirs(directory, exist_ok=True)
    written = []
    n = 0
    for p in plan.providers.values():
        n += 1
        secret = f"{p['tyk_slug'].upper().replace('-', '_')}_KEY"
        path = os.path.join(directory, f"{n:02d}-secret-{p['tyk_slug']}.json")
        with open(path, "w") as fh:
            json.dump(jsonapi("secrets", {"var_name": secret, "value": "<paste the vendor key>"}), fh, indent=2)
        written.append(path)
        n += 1
        attrs = {
            "name": p["tyk_slug"], "vendor": p["vendor"],
            "api_endpoint": p["custom_host"] or "<vendor API endpoint, e.g. https://api.openai.com/v1>",
            "api_key": f"$SECRET/{secret}",
            "default_model": next((m for m in p["models"] if m), "<default model>"),
            "allowed_models": [f"^{re.escape(m)}$" for m in p["models"] if m] or ["<regex>"],
            "privacy_score": 50, "active": True,
        }
        if p["vendor"] == "bedrock":
            attrs.pop("api_key")
            attrs["metadata"] = {"aws_access_key_id": f"$SECRET/{secret}_ID", "aws_secret_access_key": f"$SECRET/{secret}"}
        fo = plan.failover.get(p["tyk_slug"])
        if fo:
            attrs["failover"] = {"targets": [{"llm_id": f"<id of {t['tyk_slug']}>", "model": t["model"]} for t in fo["targets"]],
                                 "triggers": fo["triggers"]}
        path = os.path.join(directory, f"{n:02d}-llm-{p['tyk_slug']}.json")
        with open(path, "w") as fh:
            json.dump(jsonapi("llms", attrs), fh, indent=2)
        written.append(path)
    if plan.router:
        n += 1
        r = plan.router
        body = jsonapi("model-routers", {
            "name": r["slug"], "slug": r["slug"], "active": True,
            "pools": [{"name": r["pool"], "model_pattern": r["model_pattern"], "selection_algorithm": r["algorithm"], "priority": 10,
                       "vendors": [{"llm_id": f"<id of {v['tyk_slug']}>", "weight": v["weight"], "active": True,
                                    "mappings": [{"source_model": r["source_model"], "target_model": v["model"]}]} for v in r["vendors"]]}],
        })
        path = os.path.join(directory, f"{n:02d}-model-router-{r['slug']}.json")
        with open(path, "w") as fh:
            json.dump(body, fh, indent=2)
        written.append(path)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="Portkey Config JSON file, or - for stdin")
    ap.add_argument("--name", help="name for the plan (default: file name)")
    ap.add_argument("--slug-map", help="JSON file mapping Portkey provider slugs to Tyk provider slugs")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON instead of Markdown")
    ap.add_argument("--payloads", metavar="DIR", help="also write JSON:API request bodies into DIR")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.config == "-" else open(args.config).read()
    cfg = json.loads(raw)
    if isinstance(cfg, dict) and "config" in cfg and isinstance(cfg["config"], dict) and "strategy" not in cfg:
        cfg = cfg["config"]  # a GET /configs/{slug} envelope
    if isinstance(cfg, dict) and "data" in cfg and isinstance(cfg["data"], dict) and "config" in cfg["data"]:
        cfg = cfg["data"]["config"]
    name = args.name or (os.path.splitext(os.path.basename(args.config))[0] if args.config != "-" else "config")
    slug_map = json.load(open(args.slug_map)) if args.slug_map else {}

    plan = translate(cfg, name, slug_map)
    if args.json:
        print(json.dumps({"name": plan.name, "providers": list(plan.providers.values()), "failover": plan.failover,
                          "router": plan.router, "conditional": plan.conditional, "cache": plan.cache,
                          "filters": plan.filters, "manual": plan.manual, "notes": plan.notes}, indent=2))
    else:
        print(render_markdown(plan))
    if args.payloads:
        files = write_payloads(plan, args.payloads)
        print(f"\nWrote {len(files)} payload file(s) to {args.payloads}. Replace every <placeholder>, create secrets first, then providers, then the router.", file=sys.stderr)


if __name__ == "__main__":
    main()
