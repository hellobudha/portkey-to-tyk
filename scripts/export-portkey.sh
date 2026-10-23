#!/usr/bin/env bash
# Export a Portkey organisation's configuration through the Admin API, for a migration inventory.
#
#   PORTKEY_ADMIN_KEY=pk-... ./scripts/export-portkey.sh [output-dir]
#
# Needs an ORGANISATION admin key (workspace keys only see their own workspace), curl and jq.
# Set PORTKEY_BASE_URL for a self-hosted control plane (default https://api.portkey.ai/v1).
# Provider credentials are never returned by the API; fetch those from your own vault.
# Lists are fetched with page_size=100; if a count printed below is exactly 100, page manually.
set -euo pipefail

: "${PORTKEY_ADMIN_KEY:?set PORTKEY_ADMIN_KEY to an organisation admin key}"
BASE="${PORTKEY_BASE_URL:-https://api.portkey.ai/v1}"
OUT="${1:-portkey-export-$(date +%Y%m%d)}"
for tool in curl jq; do command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }; done
mkdir -p "$OUT"

get() { # get <path> <file>
  local code
  code=$(curl -sS -o "$OUT/$2" -w '%{http_code}' -H "x-portkey-api-key: $PORTKEY_ADMIN_KEY" "$BASE$1")
  if [ "$code" != "200" ]; then echo "  ! GET $1 -> HTTP $code (kept body in $2)" >&2; fi
}
count() { jq -r '(.data // .) | if type=="array" then length else "?" end' "$OUT/$1" 2>/dev/null || echo "?"; }

echo "Exporting from $BASE into $OUT"
get /workspaces                      workspaces.json
get /api-keys                        api-keys.json
get "/integrations?page_size=100"    integrations.json
get /providers                       providers.json
get "/virtual-keys?page_size=100"    virtual-keys.json   # deprecated endpoint, still answers
get "/configs?page_size=100"         configs-index.json
get "/prompts?page_size=100"         prompts-index.json
get /guardrails                      guardrails.json
get /policies/usage-limits           usage-limits.json
get /mcp-servers                     mcp-servers.json

mkdir -p "$OUT/configs" "$OUT/prompts"
for slug in $(jq -r '.data[]?.slug // empty' "$OUT/configs-index.json"); do
  get "/configs/$slug" "configs/$slug.raw.json"
  jq '.data.config // .config // .' "$OUT/configs/$slug.raw.json" > "$OUT/configs/$slug.json" && rm -f "$OUT/configs/$slug.raw.json"
done
for id in $(jq -r '.data[]?.id // empty' "$OUT/prompts-index.json"); do
  get "/prompts/$id" "prompts/$id.json"
done

cat <<SUMMARY

Inventory
  workspaces        $(count workspaces.json)
  api keys          $(count api-keys.json)
  integrations      $(count integrations.json)
  providers         $(count providers.json)
  virtual keys      $(count virtual-keys.json)
  configs           $(count configs-index.json)   (bodies in $OUT/configs/)
  prompts           $(count prompts-index.json)   (templates in $OUT/prompts/)
  guardrails        $(count guardrails.json)
  usage policies    $(count usage-limits.json)
  mcp servers       $(count mcp-servers.json)

Next: ./scripts/translate-config.py $OUT/configs/<slug>.json
SUMMARY
