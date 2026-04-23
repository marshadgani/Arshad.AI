# API Rules — FastAPI REST Design

## URL Structure

- **Plural nouns for resources**: `/messages`, `/sessions`, `/users`
- **Kebab-case** for multi-word segments: `/conversation-sessions`
- **Nest resources** to express ownership: `/sessions/{session_id}/messages`
- **Verbs only for non-CRUD actions**: `/sessions/{id}/summarise`, `/messages/{id}/retry`
- No trailing slashes.

```
GET    /sessions                     → list sessions
POST   /sessions                     → create session
GET    /sessions/{id}                → get session
PATCH  /sessions/{id}                → partial update
DELETE /sessions/{id}                → delete session
GET    /sessions/{id}/messages       → list messages in session
POST   /sessions/{id}/messages       → send a message
```

## Request & Response Schemas

- All request/response bodies are **Pydantic v2 models**.
- Request models are named `<Action><Resource>Request`: `CreateSessionRequest`
- Response models are named `<Resource>Response`: `SessionResponse`
- Never return SQLAlchemy model objects directly — always convert to a response schema.
- Response bodies always have a consistent shape:
  ```json
  { "data": { ... } }                  // single resource
  { "data": [ ... ], "total": 42 }     // collection
  ```

## HTTP Status Codes

| Situation | Code |
|---|---|
| Successful read | 200 |
| Resource created | 201 |
| No content (delete) | 204 |
| Validation error | 422 |
| Not found | 404 |
| Unauthorised (not logged in) | 401 |
| Forbidden (logged in, wrong permissions) | 403 |
| Server error | 500 |

Never return 200 with `{ "error": "..." }` in the body. Use the correct HTTP status code.

## Error Responses

All error responses follow this shape:
```json
{
  "error": {
    "code": "session_not_found",
    "message": "No session with id 'abc-123' exists.",
    "details": {}
  }
}
```

- `code` is a machine-readable snake_case string — used by the frontend to localise or handle errors programmatically.
- `message` is human-readable English — suitable to display directly to a developer.
- `details` is optional extra context (e.g. which fields failed validation).
- Never expose stack traces, internal paths, or SQL errors to the client.

## Validation

- Validate at the boundary — Pydantic handles this for request bodies automatically.
- Use `Field(...)` constraints for lengths, ranges, and patterns:
  ```python
  content: str = Field(..., min_length=1, max_length=100_000)
  ```
- Validate foreign keys exist in the database at the service layer, not the route handler.

## Pagination

All list endpoints must be paginated. Use offset-based pagination:
```
GET /sessions/messages?limit=20&offset=0
```
Response includes `total` so the client can compute page count.
Default `limit` is 20, max is 100. Enforce the max in the route handler.

## Authentication

- All routes except `/health` and `/auth/*` require a valid bearer token.
- Use FastAPI `Depends()` for the auth check — never inline it in each route.
- The auth dependency raises `401` if the token is missing/invalid, `403` if the token is valid but lacks permissions.

## Streaming Responses

- Chat responses stream via `StreamingResponse` with `media_type="text/event-stream"`.
- Each event is a JSON-encoded chunk: `data: {"delta": "..."}\n\n`
- Send a final `data: [DONE]\n\n` event when the stream closes.
- Always set `Cache-Control: no-cache` on streaming responses.

## Versioning

- Current API is unversioned (v0/internal). When the API stabilises, prefix with `/v1/`.
- Never break existing endpoints — add new fields, don't remove or rename existing ones.
