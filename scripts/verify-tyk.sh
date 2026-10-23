#!/usr/bin/env bash
# Post-migration checks against a Tyk AI Studio gateway (run them against the EDGE gateway).
#
#   TYK_APP_SECRET=... ./scripts/verify-tyk.sh --gateway https://edge.example.com --model anthropic-prod/claude-sonnet-5-5 \
#       [--ungranted some-slug/model] [--failover-model slug/model-that-fails] [--router-model router/model] \
#       [--embed-slug slug --embed-model text-embedding-3-small] [--metrics] [--metrics-token TOKEN] [--guardrail-probe]
#
# Each check prints PASS, FAIL or SKIP; the exit code is 1 if anything failed. Needs curl and jq.
# --guardrail-probe sends a fake AWS access key id in a prompt and expects the request to be blocked (HTTP 400);
# only use it when a credentials guardrail is attached to the provider behind --model.
set -uo pipefail

GATEWAY=""; MODEL=""; UNGRANTED="no-such-provider/no-such-model"; FAILOVER_MODEL=""; ROUTER_MODEL=""
EMBED_SLUG=""; EMBED_MODEL=""; METRICS=0; METRICS_TOKEN=""; GUARDRAIL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --gateway) GATEWAY="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --ungranted) UNGRANTED="$2"; shift 2 ;;
    --failover-model) FAILOVER_MODEL="$2"; shift 2 ;;
    --router-model) ROUTER_MODEL="$2"; shift 2 ;;
    --embed-slug) EMBED_SLUG="$2"; shift 2 ;;
    --embed-model) EMBED_MODEL="$2"; shift 2 ;;
    --metrics) METRICS=1; shift ;;
    --metrics-token) METRICS=1; METRICS_TOKEN="$2"; shift 2 ;;
    --guardrail-probe) GUARDRAIL=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$GATEWAY" ] && [ -n "$MODEL" ] || { echo "usage: --gateway URL --model slug/model (see --help)" >&2; exit 2; }
: "${TYK_APP_SECRET:?set TYK_APP_SECRET to the App secret}"
for tool in curl jq; do command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }; done
GATEWAY="${GATEWAY%/}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
FAILS=0

report() { printf '%-6s %-34s %s\n' "$1" "$2" "$3"; [ "$1" = "FAIL" ] && FAILS=$((FAILS+1)); return 0; }
hdr() { grep -i "^$1:" "$TMP/h" | head -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }
chat() { # chat <model> <content> [extra-json]  -> body in $TMP/b, headers in $TMP/h, prints status
  curl -s -m 60 -o "$TMP/b" -D "$TMP/h" -w '%{http_code}' "$GATEWAY/v1/chat/completions" \
    -H "Authorization: Bearer $TYK_APP_SECRET" -H "Content-Type: application/json" \
    -d "{\"model\":\"$1\",\"max_tokens\":20,${3:-}\"messages\":[{\"role\":\"user\",\"content\":\"$2\"}]}"
}

echo "Tyk AI Studio verification against $GATEWAY"
echo

# 1. model discovery
code=$(curl -s -m 30 -o "$TMP/b" -w '%{http_code}' "$GATEWAY/v1/models" -H "Authorization: Bearer $TYK_APP_SECRET")
if [ "$code" = "200" ] && jq -e --arg m "$MODEL" '.data[]? | select(.id==$m)' "$TMP/b" >/dev/null 2>&1; then
  report PASS "GET /v1/models" "lists $MODEL ($(jq '.data|length' "$TMP/b") entries)"
elif [ "$code" = "401" ]; then report FAIL "GET /v1/models" "401: credential not activated or wrong secret"
else report FAIL "GET /v1/models" "HTTP $code, $MODEL not listed"; fi

# 2. chat completion and served headers
code=$(chat "$MODEL" "Reply with the single word OK.")
served=$(hdr X-Tyk-Served-LLM); smodel=$(hdr X-Tyk-Served-Model)
if [ "$code" = "200" ] && [ -n "$served" ]; then report PASS "POST /v1/chat/completions" "served by $served / $smodel"
else report FAIL "POST /v1/chat/completions" "HTTP $code $(jq -r '.error.message // .message // empty' "$TMP/b" 2>/dev/null | head -c 120)"; fi

# 3. streaming
first=$(curl -s -N -m 60 "$GATEWAY/v1/chat/completions" -H "Authorization: Bearer $TYK_APP_SECRET" -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"max_tokens\":20,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Count to three.\"}]}" | head -c 300)
case "$first" in data:*) report PASS "streaming" "SSE chunks received" ;; *) report FAIL "streaming" "no data: frames (${first:0:80})" ;; esac

# 4. grant enforcement
code=$(chat "$UNGRANTED" "ping")
if [ "$code" = "403" ]; then report PASS "ungranted model -> 403" "$UNGRANTED refused"
else report FAIL "ungranted model -> 403" "HTTP $code for $UNGRANTED"; fi

# 5. failover
if [ -n "$FAILOVER_MODEL" ]; then
  code=$(chat "$FAILOVER_MODEL" "ping")
  if [ "$code" = "200" ] && [ "$(hdr X-Tyk-Failover)" = "true" ]; then report PASS "failover" "X-Tyk-Failover: true, served by $(hdr X-Tyk-Served-LLM) / $(hdr X-Tyk-Served-Model)"
  else report FAIL "failover" "HTTP $code, X-Tyk-Failover='$(hdr X-Tyk-Failover)'"; fi
else report SKIP "failover" "pass --failover-model"; fi

# 6. model router
if [ -n "$ROUTER_MODEL" ]; then
  code=$(chat "$ROUTER_MODEL" "ping")
  if [ "$code" = "200" ] && [ -n "$(hdr X-Tyk-Router)" ]; then report PASS "model router" "router $(hdr X-Tyk-Router), route $(hdr X-Tyk-Route), served by $(hdr X-Tyk-Served-LLM)"
  else report FAIL "model router" "HTTP $code, no X-Tyk-Router (routers run on edge gateways only)"; fi
else report SKIP "model router" "pass --router-model"; fi

# 7. embeddings through the vendor-native passthrough
if [ -n "$EMBED_SLUG" ] && [ -n "$EMBED_MODEL" ]; then
  code=$(curl -s -m 60 -o "$TMP/b" -w '%{http_code}' "$GATEWAY/llm/call/$EMBED_SLUG/v1/embeddings" -H "Authorization: Bearer $TYK_APP_SECRET" -H "Content-Type: application/json" \
    -d "{\"model\":\"$EMBED_MODEL\",\"input\":\"hello\"}")
  dims=$(jq -r '.data[0].embedding | length' "$TMP/b" 2>/dev/null || echo 0)
  if [ "$code" = "200" ] && [ "${dims:-0}" -gt 0 ]; then report PASS "embeddings passthrough" "$dims dimensions via /llm/call/$EMBED_SLUG"
  else report FAIL "embeddings passthrough" "HTTP $code"; fi
else report SKIP "embeddings passthrough" "pass --embed-slug and --embed-model"; fi

# 8. metrics
if [ "$METRICS" = "1" ]; then
  if [ -n "$METRICS_TOKEN" ]; then code=$(curl -s -m 30 -o "$TMP/b" -w '%{http_code}' "$GATEWAY/metrics" -H "Authorization: Bearer $METRICS_TOKEN")
  else code=$(curl -s -m 30 -o "$TMP/b" -w '%{http_code}' "$GATEWAY/metrics"); fi
  if [ "$code" = "200" ] && grep -q '^gen_ai_' "$TMP/b"; then report PASS "/metrics" "$(grep -c '^gen_ai_\|^aistudio_' "$TMP/b") gen_ai_/aistudio_ lines"
  else report FAIL "/metrics" "HTTP $code (needs METRICS_AUTH_TOKEN or METRICS_ALLOW_UNAUTHENTICATED=true)"; fi
else report SKIP "/metrics" "pass --metrics or --metrics-token"; fi

# 9. guardrail probe
if [ "$GUARDRAIL" = "1" ]; then
  code=$(chat "$MODEL" "Use key AKIAIOSFODNN7EXAMPLE for the deployment.")
  if [ "$code" = "400" ] && grep -qi "policy" "$TMP/b"; then report PASS "guardrail block" "400: $(jq -r '.error.message' "$TMP/b" | head -c 100)"
  else report FAIL "guardrail block" "HTTP $code; is a credentials guardrail attached to this provider?"; fi
else report SKIP "guardrail block" "pass --guardrail-probe"; fi

echo
if [ "$FAILS" -gt 0 ]; then echo "$FAILS check(s) failed"; exit 1; else echo "all run checks passed"; fi
