# ai-core Domain

Claude AI orchestration — tool dispatch, context management, streaming responses

## Agents

- [chat-orchestrator](agents/chat-orchestrator/README.md)
- [tool-dispatcher](agents/tool-dispatcher/README.md)
- [context-manager](agents/context-manager/README.md)
- [response-streamer](agents/response-streamer/README.md)

## Application

ChatApp — main chat interface connecting to the orchestrator

## Branch

`domain/ai-core` — integration branch for all ai-core agents.
Merge path: `agent/ai-core/*` → `domain/ai-core` → `develop` → `main`
