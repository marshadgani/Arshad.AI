# Infrastructure

Shared infrastructure components used by all domains.

| Component | Purpose |
|---|---|
| `api-gateway/` | Central routing, auth enforcement, rate limiting |
| `message-bus/` | Async event bus for domain notifications |
| `monitoring/` | Health checks, metrics, alerting config |

All inter-agent and inter-domain communication goes through `api-gateway/`.
