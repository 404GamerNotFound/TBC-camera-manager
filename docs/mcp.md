# AI interface (MCP server)

In addition to the [read API](api.md), TBC provides a
[Model Context Protocol](https://modelcontextprotocol.io/) server using Streamable HTTP at
`/mcp/mcp`. An AI agent such as Claude Desktop, Claude Code, a Claude.ai custom connector, or a
custom MCP client can query TBC directly in a structured way: “Which cameras do I have?”,
“Show me the latest motion events at the driveway”, or “What does the garden camera currently
show?” The agent does not need to learn the REST API first.

## Enabling and authentication

The MCP server shares the **same** enable switch and **same** API key as the read API under
`Admin → Settings`; see [api.md](api.md). There is no separate MCP-specific switch or key. When
the API is disabled, `/mcp/mcp` also returns `404`. When a key is required, send it as a bearer
token or through the `X-API-Key` header, exactly as for the read API:

```text
Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

## Client configuration

**Claude Code:**

```bash
claude mcp add --transport http tbc https://tbc.example.com/mcp/mcp \
  --header "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

**Generic configuration** for MCP clients that use a configuration file:

```json
{
  "mcpServers": {
    "tbc": {
      "url": "https://tbc.example.com/mcp/mcp",
      "headers": {
        "Authorization": "Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
      }
    }
  }
}
```

**Claude.ai / Claude Desktop:** Add TBC as a custom connector using the endpoint URL and the
same authorization header. Exact steps vary by client version.

## Available tools

Every tool is read-only and mirrors the [read API](api.md). Each tool calls the same
`database.py` functions rather than maintaining separate logic.

| Tool | Description |
|---|---|
| `list_cameras` | All cameras with capabilities and status |
| `get_camera` | One camera by ID |
| `get_camera_detections` | Current detection state for a camera |
| `get_camera_snapshot` | Current live preview for a camera, returned as an image rather than only a URL |
| `list_recordings` | Recording list, filterable by camera, detection type, and date range |
| `get_recording` | Metadata for one recording |
| `get_recording_snapshot` | Event preview for a recording, available only for a locally stored snapshot |
| `get_activity` | Event recordings across all cameras for one day |
| `get_storage` | Configured storage targets without credentials |
| `get_health` | System utilization, health status, and health events |
| `get_status` | Application name, version, update availability, and camera count |

As with the read API, camera credentials, storage or S3 secrets, and the API-key hash never
appear in tool responses. `get_camera_snapshot` and `get_recording_snapshot` return the image
content directly rather than a link, allowing an agent to inspect what a camera currently
shows or what was detected during an event.

## Known limitations

- Video clips are intentionally not exposed as a dedicated tool because there is no useful
  response format for a language model. `get_recording` still includes `media_url` for
  downstream systems that need to access the clip.
- `get_recording_snapshot` works only for locally stored recordings. If a recording exists
  exclusively in S3-compatible storage without a local copy, the tool returns an error rather
  than a download.
