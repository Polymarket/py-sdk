# Platform API Keys

Application attribution is separate from signer authentication, signed trading
orders, builder authorization and gasless quota. A key-bound challenge establishes
the session's `client_id` on the server. The SDK has no `client_id` override.

Use `PlatformApiKey` only on a server. It follows Python's existing `BuilderApiKey`
and `RelayerApiKey` adapter convention; the TypeScript spelling is `platformApiKey`.
Both `SecureClient` and `AsyncSecureClient` accept the same configuration:

```python
from polymarket import PlatformApiKey, SecureClient

with SecureClient.create(
    private_key=load_private_key(),
    wallet=wallet_address,
    api_key=PlatformApiKey(key=load_server_platform_key()),
) as client:
    orders = client.list_open_orders().first_page()
```

`PublicClient(api_key=PlatformApiKey(...))` also supports `login` and
`migrate_credentials`. Configured public reads and authenticated prediction
requests use the gateway. The adapter sends `X-API-Key` to gateway challenge,
login, migration and ordinary requests. Refresh and logout go directly to the
gateway without that header. They reuse the same bearer session and its timer,
retry, callback, cancellation and cleanup behavior.

Restoring credentials with a direct Platform key refreshes the pair and checks
the refreshed bearer/key association at the gateway before adoption or persistence. A conflicting key raises
`RequestRejectedError`; it cannot overwrite the bound application identity.

## Challenge-only proxy

`RemotePlatformApiKey` contains only the integrator's challenge endpoint. Python
requires an absolute HTTP(S) URL because it has no browser origin to resolve a
relative URL against. The endpoint is called exactly as supplied, including its
path and query; no suffix is appended. The equivalent TypeScript adapter is
`remotePlatformApiKey`.

```python
from polymarket import RemotePlatformApiKey, SecureClient

with SecureClient.create(
    private_key=load_private_key(),
    wallet=wallet_address,
    api_key=RemotePlatformApiKey(url="https://your-app.example/api/auth/challenge"),
) as client:
    orders = client.list_open_orders().first_page()
```

The proxy receives only challenge inputs: signer, optional wallet, verification
token and nonce. The SDK signs the returned typed data and submits the signature
directly to the gateway. The proxy receives no wallet signature or bearer token,
and the SDK's remote configuration contains no Platform API Key. Refresh and
logout never use the proxy.

The backend must authenticate its caller and authorize the requested signer/wallet.
Do not deploy an unrestricted challenge relay. This FastAPI sketch shows the
boundary; `require_authenticated_caller`, `require_authorized_signer` and
`load_server_platform_key` are application-owned functions. FastAPI is not an SDK
dependency. Return `Cache-Control: no-store` on successful and rejected responses:

```python
import httpx
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI()

class ChallengeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signer: str
    wallet: str | None = None
    verification_token: str | None = None
    nonce: int = Field(default=0, ge=0, le=4294967295)

@app.post("/api/auth/challenge")
async def challenge(request: Request) -> Response:
    caller = await require_authenticated_caller(request)
    body = ChallengeInput.model_validate(await request.json())
    await require_authorized_signer(caller, body.signer, body.wallet)
    async with httpx.AsyncClient() as http:
        upstream = await http.post(
            "https://api.defi.polymarket.com/v1/auth/challenge",
            json=body.model_dump(exclude_none=True),
            headers={"X-API-Key": load_server_platform_key()},
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
```

Apply your application's no-store error handling to authentication, authorization
and validation failures before the upstream call too. Do not log request/response
bodies, signatures or credentials. Keep Platform keys out of returned JSON,
configuration served to browsers, storage accessible to browsers and traces.
The SDK redacts its authentication error messages and suppresses raw WebSocket
frame logging. Application-supplied logging and HTTP hooks must honor the same rule.

A remote challenge adapter cannot attribute a signature-free legacy migration.
That configuration raises `UserInputError` rather than silently creating an
unattributed session. Migrate server-side with `PlatformApiKey`, save the returned
bearer pair, and restore it, or perform a fresh remote challenge login. Restoring a
remote-configured client preserves the existing session's server-bound attribution;
changing a proxy URL does not rebind saved credentials.

## Legacy authorization during migration

Keep existing `api_key=BuilderApiKey(...)` and `api_key=RelayerApiKey(...)` workflows
when they are required. To add Platform attribution to such a client, move the
existing key to `legacy_api_key`; do not discard it:

```python
from polymarket import BuilderApiKey, PlatformApiKey, SecureClient

# Before
legacy_key = BuilderApiKey(**load_legacy_builder_key())
client = SecureClient.create(private_key=load_private_key(), api_key=legacy_key)
client.close()

# After: the same legacy key continues authorizing downstream operations.
with SecureClient.create(
    private_key=load_private_key(),
    api_key=PlatformApiKey(key=load_server_platform_key()),
    legacy_api_key=legacy_key,
) as client:
    orders = client.list_open_orders().first_page()
```

The same `legacy_api_key` option accepts `RelayerApiKey`. Passing legacy keys through
both options is rejected. Platform and legacy authentication are not mixed into
account L2 credentials; signed orders still retain their trading signature and
owner key identifier. Legacy builder/relayer credentials go only to the existing
workflows that require them. Perps keeps its separate authentication.

Platform attribution alone does not establish builder identity or gasless quota
continuity. External release must verify that backend mapping; no fallback is
invented and no legacy key retirement is authorized. Third-party browser release
also needs external-origin CORS/edge verification and the deployed authentication
and WebSocket renewal contracts. Python synthetic tests do not establish browser
bundle boundaries or production deployment readiness.
