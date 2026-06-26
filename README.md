# raphael-workspaces

Workspaces, modules, commits, diffs, branching, history

## API

- Prefix: `/v1/workspaces`
- Port: `8083`
- Health: `GET /health`

## Events

_Published and consumed events documented in `openapi.yaml` and raphael-contracts._

## Development

```bash
uv sync
uv run uvicorn raphael_workspaces.app:app --reload --port 8083
```

Part of the [Raphael Platform](https://github.com/hummingbird-labs) by HummingBird Labs.
