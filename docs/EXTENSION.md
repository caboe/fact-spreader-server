# Extension connection

The browser extension lives in its own repository
([fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader)); this
repository provides the server side and the connection flow. This document is for the
person maintaining the fork: what the server expects, how the one-time handoff works and
which parts of the wire format are stable.

## 1. Create a device token

1. Sign in to Fact Spreader and open **Connect plugin** (`/connect`).
2. Enter a device name (for example `Firefox on macOS`) and create the token.
3. The plaintext `fc_dev_…` token is shown once. Only its hash is stored on the server.
4. Revoke it on the same page when the browser is no longer used. Revocation is immediate.

The token defaults to the `claims:submit` permission and can never exceed the owner's
permissions (`PROTOCOL §11`). It cannot review documents or change settings. The
`GET /v1/devices` list and `DELETE /v1/devices/{id}` require the owner or `devices:manage`.

## 2. One-time handoff

The extension opens the page as a popup with a random `state`:

```
https://<host>/connect?state=<nonce>
```

The user creates the token in that tab. Because the tab was opened by the extension page,
`document.referrer` is the extension origin (`chrome-extension://…` or `moz-extension://…`).
After creation the page posts:

```json
{
  "type": "fs-device-token",
  "state": "<same nonce>",
  "token": "fc_dev_…"
}
```

with `window.opener.postMessage(message, extensionOrigin)`. The extension verifies the
`state` it generated, stores the token in its own storage and closes the tab. A token is
only posted when the opener's origin is an extension origin, and the token never appears in
a URL or a server log. The user can copy the token manually if the automatic handoff is not
used.

The server never sends the token anywhere; the handoff is between the page and the
extension.

## 3. Submitting a check

Send the token as a bearer credential. CORS: set `CORS_EXTENSION_ORIGINS` to the extension
IDs the deployment trusts, for example:

```dotenv
CORS_EXTENSION_ORIGINS=chrome-extension://abcdefghijklmnop,moz-extension://11111111-2222-3333-4444-555555555555
```

No wildcard and no credentials. A compact check:

```http
POST /v1/factcheck
Authorization: Bearer fc_dev_…
Content-Type: application/json
```

```json
{
  "input": {"type": "text", "text": "The claim the user selected"},
  "output_format": "compact",
  "mode": "async",
  "response_language": "en"
}
```

The response is `202` with a `job`; poll `GET /v1/factcheck/{job_id}` until `done` and read
`result.compact` (`PROTOCOL §3.8`, §5). The compact report contains the verdict,
`verdict_label`, `bottom_line`, `missing_contexts`, two or three `key_evidence` entries and
`report_url`. It is deterministic, localized template output; the extension shows it and
offers **Open the full report**, which opens `report_url` in the web app.

For a synchronous check, `"mode": "sync"` returns the same result in one request when the
pipeline finishes inside the request budget; the extension should prefer async for long
inputs. Images are limited by the server's upload limits
(`USER_MAX_FILE_BYTES`, default 20 MB); downscale screenshots to roughly 1600 px on the
long edge before upload. Files and URLs use the same endpoint with `input.type` `file` or
`url`.

## 4. What the extension must not do

- Do not send claim text or the token to the inference provider; all model calls go through
  the server's gateway.
- Do not cache the token in `localStorage` on a normal web page; keep it in extension
  storage.
- Do not treat the compact report as a verdict the extension can edit. It is display-only;
  the server computed it from structured output and code.
- Do not call the internal `/internal/v1` gateway; it is not exposed through Caddy.

## 5. Testing the fork against this stack

```bash
make stack-up
# create the token in the UI, then from the extension:
curl -s http://localhost:8000/v1/instance
```

A check with a device token can be exercised without the extension:

```bash
curl -s -X POST http://localhost:8000/v1/factcheck \
  -H "Authorization: Bearer $FS_DEVICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"input":{"type":"text","text":"The Berlin Wall fell in 1989."},"output_format":"compact"}'
```

Then poll the `job.id`. Revoking the device makes the same request return `401` on the next
call.
