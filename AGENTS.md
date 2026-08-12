# Agent Instructions

## Tooling

- Use `uv` for dependency management, testing, and builds.

## Review Method

- Review from the developer workflow inward. Start by understanding what the consumer is trying to accomplish and inspect realistic usage examples.
- Build a complete mental model before judging the implementation. Clarify terminology, lifecycle, ownership, and failure behavior.
- Review the public contract first: naming, symmetry, defaults, state representation, validation, errors, and call-site ergonomics.
- Separate SDK behavior, integrator behavior, documentation examples, and backend behavior. Attach findings to the layer that owns them.
- Compare questionable code with established repository patterns before requesting a change.
- Evaluate findings by practical impact. Downgrade or discard concerns when the risk is bounded and the proposed complexity is not justified.
- Prefer tests that prove meaningful boundaries. Favor one live integration workflow over multiple mocks when a safe test environment exists.
- Use mocks for conditions that cannot reasonably be produced through integration testing.
- Distinguish demonstrated bugs, contract problems, missing regression coverage, and optional hardening.
- Revisit initial findings as understanding improves rather than defending the first interpretation.
- Keep review comments short, human, line-specific, and actionable.

## SDK Design

- Keep the PyPI distribution name as `polymarket-client` and the import package as `polymarket` unless explicitly changed.
- When implementing new areas where guidance is vague, choose the most idiomatic Python approach but avoid premature abstractions.
- Prefer simple, direct code until there is a concrete repeated use case or public API need that justifies a helper, wrapper, protocol, base class, or configuration abstraction.
- Do not copy TypeScript SDK shapes mechanically; preserve feature parity while adapting APIs to Python ecosystem norms and the smallest useful surface.
- The SDK should present one cohesive consumer interface and hide current service boundaries where possible.
- Design public APIs around developer workflows rather than the current split between underlying APIs.
- Do not mirror today's service fragmentation directly in the public SDK surface.
- Public docs and docstrings should describe the unified SDK behavior; avoid mentioning underlying service names unless the user specifically asks, a low-level escape hatch requires it, or a test needs to document a boundary.
- In public-facing docs, docstrings, type descriptions, and examples, describe SDK objects directly as the objects users work with. Do not mention that objects are normalized from raw responses, hide uneven internal/API surfaces, or frame models around which backend currently provides data.
- Lower-level controls are acceptable when they support a concrete integration need, but the default experience should feel unified.
- For internal invariant checks, use Python-native `RuntimeError`, `AssertionError`, or `typing.assert_never` as appropriate instead of introducing a public `InvariantError` SDK exception.
- Use `typing.NewType` selectively for meaningful SDK domain types. Generic primitives such as `EvmAddress`, `HexString`, and `TransactionHash` belong outside `polymarket.models`; model-specific identifiers such as `MarketId`, `EventId`, `ConditionId`, `TokenId`, and `OrderId` belong under `polymarket.models` and should be re-exported from the public package where useful.
- Do not mark every primitive field. Prefer marked types for key identifiers and domain concepts where the IDE/type name adds meaning or prevents confusion. Keep public method inputs developer-friendly by accepting plain primitives like `str` unless stricter typing has a concrete benefit; returned models may expose marked types.
- Name request/path construction helpers with `build_*`.
- Do not rename existing variables, functions, or classes unless the operator explicitly asks for it in the prompt. Keep PRs lean; if a name looks wrong, propose the rename as a separate change instead of bundling it.
- Avoid reuse that does not carry semantic or domain-specific value. Do not add boolean mode flags or generic helpers that hide distinct behavior behind one function; prefer separate explicit helpers whose names describe the behavior they implement.

## Public Model Types

- Public model fields and generated constructor signatures must expose canonical Python value types such as `Decimal`, `datetime`, and domain enums, not wire-format names or validation-only `Annotated` aliases.
- Do not use `TYPE_CHECKING` branches to give static tooling a different type definition from the one available at runtime. Keep static annotations, runtime introspection, and generated documentation consistent.
- Normalize incoming wire values at the response boundary with field validators or explicit response parsing. Keep format-specific behavior, such as decimal strings, E6 integer strings, and distinct timestamp encodings, in clearly named parsers rather than broad shared aliases.
- Construct outgoing request payloads explicitly at the request boundary, including unit scaling and string conversion. Do not rely on response-model serializers to satisfy request protocols, and only add a model serializer when JSON serialization is itself part of the model's documented public contract.
- Preserve `Annotated` metadata that expresses real type semantics, such as discriminators or constraints. The restriction is on validation-only metadata leaking into the public type surface, not on `Annotated` itself.

## Platform Invariants

- A market's minimum tick size may become finer, such as `0.01` to `0.001`, but it cannot become coarser, such as `0.001` to `0.01`. SDK caching and recovery logic may rely on this monotonic behavior and should not add defensive handling for tick-size coarsening.
- When a Perps order is submitted with a client order ID, every corresponding private order update echoes that same client order ID. SDK order-placement workflows may rely on this invariant for pre-acknowledgement correlation.

## Client Sync/Async Design

- For request/response workflows supported by both client modes, the default public clients should be synchronous: use `PublicClient` and `SecureClient` for normal imports, docs, examples, notebooks, scripts, and basic bot usage.
- Async clients should be explicit alternatives named with an `Async` prefix, such as `AsyncPublicClient` and `AsyncSecureClient`.
- WebSocket-backed features are intentionally async-only. This includes realtime subscriptions and any Perps or combo workflow that requires a persistent WebSocket connection or session. Expose these workflows through the `Async` clients and use the async clients in their docs and examples.
- Do not add synchronous facades, placeholder methods, or event-loop bridges solely to create sync parity for WebSocket-only features.
- Keep sync and async method names the same for features implemented in both modes: sync methods return values directly, async methods return awaitables and are called with `await`. Async-only WebSocket features do not require a matching sync method.
- Avoid mixed-mode clients with flags such as `async_mode=True`, and avoid adding `_async` method variants to synchronous clients by default.
- Share business logic between sync and async implementations. Request construction, URL/path selection, auth/signing, serialization, validation, response parsing, models, and endpoint namespace structure should be reusable.
- Keep the transport boundary separate: synchronous clients should use a synchronous transport, and async clients should use an asynchronous transport.
- Do not implement sync clients by calling `asyncio.run()` around async methods unless there is a specific, reviewed reason. Event-loop ownership causes issues in notebooks, async apps, tests, and agent runtimes.
- Prefer small shared request builders plus separate sync/async transport execution over duplicating endpoint method bodies.

## Tests

- Do not add low-value unit tests that only assert language mechanics, simple inheritance, imports, or direct assignment. Prefer tests that cover SDK behavior, meaningful validation, error mapping, serialization, request construction, or user-visible workflows.
- Do not add live trading tests to the default test suite.
- Mark live service tests with `@pytest.mark.integration`.
- Integration tests that need secrets must use the `require_env` fixture from `tests/integration/conftest.py`; do not read secret env vars at import time.
- New integration tests should use shared fixtures from `tests/integration/conftest.py` for API keys, signer private keys, wallet addresses, and clients. Do not add local ad-hoc env helper functions in individual test files.
- For most new authenticated integration tests, prefer the fixture-created `deposit_wallet_client`. Create bespoke `AsyncSecureClient` or `SecureClient` instances only when the test specifically needs a different wallet type, a sync client, custom auth, or another edge-case setup; still inject the key material and addresses through fixtures.
- Do not refactor older ad-hoc integration tests unless specifically asked. Apply this fixture-based style to new tests and to files already being intentionally changed.
- Keep `.env.example` as the source of truth for local integration-test env names. Do not duplicate the full env list in Markdown files.
- Keep `.env` and real secrets uncommitted. GitHub Actions should receive integration secrets through repository or environment secrets/variables.
- Tests that place orders, spend funds, or mutate live state must also use `@pytest.mark.metered`; they are skipped unless `POLYMARKET_RUN_METERED_TESTS=1` is set.
- Document any metered test's live side effects near the test.

## Releases

- During initial development, do not assume every merged change needs its own changelog entry or published release.
- Do not merge or generate a release PR until the SDK has a meaningful first beta surface and the user explicitly asks for release preparation.
- For the first published package, prefer one manually curated changelog entry for the initial beta release instead of listing every setup/early-development change.
- Use PEP 440 pre-release versions for beta/RC publishing, such as `0.1.0b1` or `0.1.0rc1`.
- Use Conventional Commit subjects and PR titles because release-please classifies changes from commits on `main`.
- If using squash merges, the squash commit title should match the Conventional Commit PR title.
