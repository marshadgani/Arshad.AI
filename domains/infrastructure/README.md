# infrastructure Domain

Core services — API gateway, auth, cache, health monitoring

## Agents

- [api-gateway](agents/api-gateway/README.md)
- [auth-manager](agents/auth-manager/README.md)
- [cache-manager](agents/cache-manager/README.md)
- [health-monitor](agents/health-monitor/README.md)

## Application

AdminApp — service health dashboard and API gateway metrics

## Branch

`domain/infrastructure` — integration branch for all infrastructure agents.
Merge path: `agent/infrastructure/*` → `domain/infrastructure` → `develop` → `main`
