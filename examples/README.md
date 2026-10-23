# Examples

| File | What it is |
|---|---|
| `portkey-config.json` | The representative Portkey Config from section 8 of the guide: weighted split with a nested fallback, retry, simple cache, timeout, guardrails |
| `portkey-config-fallback.json` | A plain fallback chain with a circuit breaker (which has no Tyk equivalent) |
| `portkey-config-conditional.json` | Conditional routing on metadata and model name (manual in Tyk) |
| `slug-map.json` | Optional mapping from Portkey provider slugs to the Tyk provider slugs you intend to use |
| `tyk/secret.json` | `POST /api/v1/secrets` body |
| `tyk/llm-provider-with-failover.json` | `POST /api/v1/llms` body with a failover list (the `failover` attribute is accepted on 2.2.2 but is not in the published OpenAPI document) |
| `tyk/app.json` | `POST /api/v1/apps` body; activate the credential afterwards with `POST /api/v1/apps/{id}/activate-credential` |
| `tyk/model-price.json` | `POST /api/v1/model-prices` body; prices are **per token** on the API |
| `tyk/model-router.json` | `POST /api/v1/model-routers` body; `weight` must be an integer |
| `tyk/filter-script.json` | `POST /api/v1/filters` body; the script goes in **base64** (the test endpoint `POST /api/v1/filters/test` takes it as plain text) |
| `filters/pii-shield.tengo` | Request filter: block card numbers and SSNs, redact email addresses and phone numbers, raise compliance events |
| `filters/no-financial-promises.tengo` | Response filter: block promised outcomes and guaranteed-return language, streaming aware |

Try the translator on the configs:

```bash
./scripts/translate-config.py examples/portkey-config.json --slug-map examples/slug-map.json
./scripts/translate-config.py examples/portkey-config.json --payloads out/ --json > plan.json
```

Encode a filter for the create endpoint:

```bash
jq --rawfile s examples/filters/pii-shield.tengo '.data.attributes.script = ($s | @base64)' examples/tyk/filter-script.json
```

All bodies use the JSON:API envelope and `Authorization: Bearer <user API key>` against `http://<hub>/api/v1/...`. Replace every `<placeholder>`. Remember that `PATCH` on an App replaces omitted fields, so send full attribute sets.
