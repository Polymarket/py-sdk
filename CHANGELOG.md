# Changelog

## [0.7.1](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.7.0...polymarket-client-v0.7.1) (2026-08-28)


### Bug Fixes

* **session-keys:** default session key expiration ([f8fd790](https://github.com/Polymarket/py-sdk/commit/f8fd7903dc8b3b42adb027e3b23283aabb4b4cff))
* **session-keys:** default session key expiration ([c24567c](https://github.com/Polymarket/py-sdk/commit/c24567c1130a1ad3142523f1774d4aa8761b69bd))
* **session-keys:** hide authorization expiration ([fd93408](https://github.com/Polymarket/py-sdk/commit/fd93408329fd86704d3ee287ead67f69d81616cd))
* **session-keys:** restore expiration buffer ([c8b4346](https://github.com/Polymarket/py-sdk/commit/c8b4346447bc4b2b1532485f7dd9cd270363b3fa))

## [0.7.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.6.0...polymarket-client-v0.7.0) (2026-08-26)


### Features

* add scoped session keys ([#276](https://github.com/Polymarket/py-sdk/issues/276)) ([aca3b8f](https://github.com/Polymarket/py-sdk/commit/aca3b8fc7bc9a486d8dbc9ca9faaafacca4ed5ef))
* **errors:** expose typed trading restrictions for engine restarts and restricted modes ([#214](https://github.com/Polymarket/py-sdk/issues/214)) ([c8fb84b](https://github.com/Polymarket/py-sdk/commit/c8fb84bb51e60f790239056be7be0f5cc337d2e0))
* expose trading approvals state (DEV-565) ([#262](https://github.com/Polymarket/py-sdk/issues/262)) ([1f1bd63](https://github.com/Polymarket/py-sdk/commit/1f1bd63e32351819c89414c76e41b0490cd444c2))
* **models:** type notification payloads per notification kind ([fcace0e](https://github.com/Polymarket/py-sdk/commit/fcace0e6bd4c5388a3656a11700df70c1510a6ca))
* surface Poly-RateLimit state on rate-limit errors and via on_rate_limit_update ([#221](https://github.com/Polymarket/py-sdk/issues/221)) ([9fec251](https://github.com/Polymarket/py-sdk/commit/9fec25132d0b98525580650b3089946d3803e7d5))


### Bug Fixes

* **ci:** resolve release in explicit repository ([#267](https://github.com/Polymarket/py-sdk/issues/267)) ([075b848](https://github.com/Polymarket/py-sdk/commit/075b84864511f23b6ac93f0ac74fdd659abebfe3))
* **models:** align notification payload contracts ([54d5bc7](https://github.com/Polymarket/py-sdk/commit/54d5bc71b6e4953dc0f3388824b2e86430aabde9))

## [0.6.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.5.0...polymarket-client-v0.6.0) (2026-08-13)


### Features

* requester-side combo RFQ support (request quote, accept, wait for fill) ([e060f34](https://github.com/Polymarket/py-sdk/commit/e060f348e637576bf000e65ad0c12464b4e10508))


### Bug Fixes

* align combo RFQ requester behavior ([a5b5c75](https://github.com/Polymarket/py-sdk/commit/a5b5c757a777fd0e8dc3ed65f353f94f9c569a90))
* **client:** handle tokens without trades ([39b9075](https://github.com/Polymarket/py-sdk/commit/39b90750c0ff4034be32f2db623d4ed4fa74a729))
* **client:** return None for tokens without trades ([dbd0559](https://github.com/Polymarket/py-sdk/commit/dbd05590b925449a6024cfe9dbe28f10f8aecbf0))
* harden combo requester quote handling ([215ffa7](https://github.com/Polymarket/py-sdk/commit/215ffa71c234670522097171ebd86d133485e7c5))
* use resolved config for combo RFQ ([10f48ee](https://github.com/Polymarket/py-sdk/commit/10f48ee2c5b0235f3d2972817d1536353d872dc6))


### Documentation

* **client:** clarify sparse last trade batches ([e5a0b19](https://github.com/Polymarket/py-sdk/commit/e5a0b1963ad5943e087fa1d16d36e2284257d3f8))

## [0.5.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.4.0...polymarket-client-v0.5.0) (2026-08-07)


### Features

* **client:** cache order market metadata ([9e8fd4d](https://github.com/Polymarket/py-sdk/commit/9e8fd4d14adb95248fa0500dc1a544a2f4684c2f))
* **perps:** add auto-cancel support ([c5c97b0](https://github.com/Polymarket/py-sdk/commit/c5c97b0ea50a224465ca2c2468beab89de87ab64))
* **perps:** add id to funding payment records ([3187d48](https://github.com/Polymarket/py-sdk/commit/3187d4839b3c51609b5bf1ef23195ccc780fbc1d))
* **perps:** add id to funding payment records ([bf2f0d3](https://github.com/Polymarket/py-sdk/commit/bf2f0d3e1c00527a4b3fa1c35fee708f00001c84))


### Bug Fixes

* match tagged TOML package name ([c0ba4c2](https://github.com/Polymarket/py-sdk/commit/c0ba4c2cbbd7643126b86a22b65386e8afe816a3))
* **perps:** prevent order update race ([1060794](https://github.com/Polymarket/py-sdk/commit/10607940d38ef67d1f0b7dcae47709bdd3140801))
* **perps:** prevent order update race ([f4afcc9](https://github.com/Polymarket/py-sdk/commit/f4afcc91f4a7fc7cfd94dc3daf01b8886629ad09))

## [0.4.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.3.0...polymarket-client-v0.4.0) (2026-08-05)


### Features

* support isolated margin adjustments ([0fc001d](https://github.com/Polymarket/py-sdk/commit/0fc001d7ab21f64e01a937df9b2e6996564fdccc))
* support isolated margin adjustments ([7155918](https://github.com/Polymarket/py-sdk/commit/7155918966e59d1eb0dee777f977a5a8a57f27a1))


### Bug Fixes

* avoid delayed markets in order tests ([a231997](https://github.com/Polymarket/py-sdk/commit/a231997f65ecc2bd7329f0acf83fd0abe35f5907))


### Documentation

* add Python API reference artifact pipeline ([f6611c7](https://github.com/Polymarket/py-sdk/commit/f6611c74cb8a4b6fa683f463722ca1c3ce54423f))
* add Python API reference artifact pipeline ([049fe0d](https://github.com/Polymarket/py-sdk/commit/049fe0d8006265fb260ab59722428bc1f93e5c12))
* avoid conflict-like reference headings ([a5ca9e9](https://github.com/Polymarket/py-sdk/commit/a5ca9e9b14009509ba753164a500f700eac05038))
* **repo:** add review method guidance ([ef31dff](https://github.com/Polymarket/py-sdk/commit/ef31dff308148e62701fffa52d4b7979d77bb54c))
* **repo:** add review method guidance ([7bb0940](https://github.com/Polymarket/py-sdk/commit/7bb094035a7bdaf09ce9ad94b85e33531a89741f))
* **repo:** document tick-size invariant ([6021381](https://github.com/Polymarket/py-sdk/commit/6021381ec2731414e9350b255954ea2b25c5b2f6))
* **repo:** document tick-size platform invariant ([df01e80](https://github.com/Polymarket/py-sdk/commit/df01e80ac39d0599dd8a52f1867620d9168b02ef))

## [0.3.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.3.0-b2...polymarket-client-v0.3.0) (2026-08-04)


### Features

* prepare Python SDK for stable 0.3.0 ([12c59aa](https://github.com/Polymarket/py-sdk/commit/12c59aa9ca2af4a1147beb9749694f3714e98f6b))
* prepare Python SDK for stable 0.3.0 ([1f67eeb](https://github.com/Polymarket/py-sdk/commit/1f67eeb11a1880250e46338ae5185ee3fa605106))


### Bug Fixes

* include deposits and withdrawals in list_activity by default ([25a556b](https://github.com/Polymarket/py-sdk/commit/25a556bcc3cce5f5889aea80cedaa975b6ba9712))
* include deposits and withdrawals in list_activity by default ([581c9ac](https://github.com/Polymarket/py-sdk/commit/581c9ac88eebc503272ed4ba0b7fadd875e89a2c))


### Documentation

* clarify async-only WebSocket features ([d6b96ad](https://github.com/Polymarket/py-sdk/commit/d6b96adb2b4bdfbeb4739ee023b5606fd08dc05f))
* clarify async-only WebSocket features ([c9d8f38](https://github.com/Polymarket/py-sdk/commit/c9d8f386effb0bacb81e22110dcef28b187a6263))

## [0.3.0-b2](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.3.0-b1...polymarket-client-v0.3.0-b2) (2026-07-31)


### Bug Fixes

* **relayer:** self-heal deposit wallet nonce on submit rejection ([d711cd1](https://github.com/Polymarket/py-sdk/commit/d711cd19d54b9275e94e41ce366a91da3c818db4))
* support TAKER_REBATE, DEPOSIT, and WITHDRAWAL activity types ([c426bc7](https://github.com/Polymarket/py-sdk/commit/c426bc7eb9a685fa273efa74e74fcec544eb4763))

## [0.3.0-b1](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.2.0...polymarket-client-v0.3.0-b1) (2026-07-29)


### Features

* add Chainlink TWAP subscriptions ([3094295](https://github.com/Polymarket/py-sdk/commit/3094295c2575bb73ec6220d8d7f71e4811747bce))
* add Chainlink TWAP subscriptions ([5bd34cf](https://github.com/Polymarket/py-sdk/commit/5bd34cf045a72b60160a29aaebe5f5c6e84b7141))
* **perps:** paginate fills with the native cursor and sort ([1b87a81](https://github.com/Polymarket/py-sdk/commit/1b87a81162ed746f4f0b9be3b2ea5f175ed41ec5))
* **perps:** support account notifications in session reads and events ([9ec77d3](https://github.com/Polymarket/py-sdk/commit/9ec77d3d12da3777e6f5afb11f43fd18c57da498))
* **rfq:** expose granular quote validation errors ([e3a3b2d](https://github.com/Polymarket/py-sdk/commit/e3a3b2d0cec7707fae1e72fe539d4a19f93ef169))
* **rfq:** expose granular quote validation errors ([91d1221](https://github.com/Polymarket/py-sdk/commit/91d1221a0cc50fb23c8fa49c4101b4e2e934276e))


### Bug Fixes

* **errors:** expose retry_after on RequestRejectedError ([338f2d7](https://github.com/Polymarket/py-sdk/commit/338f2d7ef5f18b5b8c8c347ad8d81ade82974e0a))
* **errors:** reject non-finite retry_after values ([891a413](https://github.com/Polymarket/py-sdk/commit/891a413881d738bde586320ada2493649270432f))
* **models:** type collateral return event ids as EventId ([8c78c9e](https://github.com/Polymarket/py-sdk/commit/8c78c9ea8d748f29f89a50d50d1871874954d1e1))
* **models:** type collateral return event ids as EventId ([2b781f2](https://github.com/Polymarket/py-sdk/commit/2b781f2eaef6bf51c718a6345ab7296dd1eb5ed5))


### Documentation

* **models:** clarify collateral return event ids are neg-risk ids ([e3b306a](https://github.com/Polymarket/py-sdk/commit/e3b306a12133e980f0dea4e9f439f48177c03a95))

## [0.2.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0...polymarket-client-v0.2.0) (2026-07-24)


### Features

* **client:** add collateral return plan/execute to secure clients ([b4a1b9f](https://github.com/Polymarket/py-sdk/commit/b4a1b9fb41f9a276c684a00e382d62378092c051))
* **clob:** add wait_for_order_settlement for async order settlement ([fe24c40](https://github.com/Polymarket/py-sdk/commit/fe24c401b35370499d8e46e604e77d1293511ad6))
* **collateral-return:** add collateral return plan/execute to secure clients ([735d40f](https://github.com/Polymarket/py-sdk/commit/735d40fa3bef58d77f6642b612fe90081eb80ae3))
* **models:** add fee tiers to perps fee schedule ([02d7bcc](https://github.com/Polymarket/py-sdk/commit/02d7bcca86f2c0d44f88b058398ae47d0b1aa59a))
* **models:** add isolated_only to perps instrument ([f087c2a](https://github.com/Polymarket/py-sdk/commit/f087c2a7d7d72888dda255227dbb6f6b29c4037a))


### Bug Fixes

* cap page_size on gamma offset-paginated endpoints ([e4610d3](https://github.com/Polymarket/py-sdk/commit/e4610d386df984b06e85cbee174d691da62c1ecf))
* cap page_size on offset-paginated data endpoints and tolerate clamped pagination probes ([d062bed](https://github.com/Polymarket/py-sdk/commit/d062bedf9966811f188bf6e96b1dafdce569c1d5))
* confirm frame truncation at limit page boundaries with a follow-up fetch ([02604b0](https://github.com/Polymarket/py-sdk/commit/02604b0e45d5bf67376e68a687c708c3fa55343d))
* drop pagination look-ahead probe and cap page_size at upstream limits ([54ac687](https://github.com/Polymarket/py-sdk/commit/54ac68728f1e18d970a9528b895680d96f063251))
* drop the pagination look-ahead probe and align max_page_size with upstream limits ([c9c392c](https://github.com/Polymarket/py-sdk/commit/c9c392ca76a122034e6074a1a56ff21535e7c572))
* parse zero GTC expiration as None in OpenOrder ([3f40280](https://github.com/Polymarket/py-sdk/commit/3f402806aae26a40092ba9550b313fee0a335b05))
* parse zero GTC expiration as None in OpenOrder ([f713e76](https://github.com/Polymarket/py-sdk/commit/f713e76d7493af1a20aba5860d5388b91b83070a)), closes [#191](https://github.com/Polymarket/py-sdk/issues/191)
* **perps:** add failed withdrawal status and pass unknown statuses through as strings ([fddf670](https://github.com/Polymarket/py-sdk/commit/fddf670ad09ce2093b8d611573c1df72ad62c630))
* **perps:** add failed withdrawal status and pass unknown statuses through as strings ([e344356](https://github.com/Polymarket/py-sdk/commit/e344356582692cef6ef1a4f3460ca1cfc9ec66ef))
* **perps:** validate deposit cursors against deposit statuses only ([d39737b](https://github.com/Polymarket/py-sdk/commit/d39737b32ab20d8fa73e70383fdf1a7f51b856bc))
* stop exposing per-page count as Page.total_count ([e254ab7](https://github.com/Polymarket/py-sdk/commit/e254ab79235fd3747ace1b630e6903695614b2c1))
* stop exposing per-page count as Page.total_count ([2d578a3](https://github.com/Polymarket/py-sdk/commit/2d578a36a67e37d6a464f298859a2cfae2362b8b))

## [0.1.0](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b21...polymarket-client-v0.1.0) (2026-07-22)


### Features

* **clob:** add condition_id alias to CLOB models, deprecate market ([3940237](https://github.com/Polymarket/py-sdk/commit/3940237aa34464b422ed5dcbbb82f59ade7cb857))
* **models:** type cancellation result order IDs with OrderId ([a754f2f](https://github.com/Polymarket/py-sdk/commit/a754f2f53859ff40c99d10d9337239c9f7a1a37a))
* **models:** type cancellation result order IDs with OrderId ([f8cd831](https://github.com/Polymarket/py-sdk/commit/f8cd8317b76a3419a4d1f4dcdb32e8c16c62fc17))
* prepare Python SDK for stable 0.x ([27906ec](https://github.com/Polymarket/py-sdk/commit/27906ec4ba23101bbc63aacee829b337f839552d))
* prepare Python SDK for stable 0.x ([5b3f256](https://github.com/Polymarket/py-sdk/commit/5b3f25687a181f5d9ba9110b13c6c8167b6adfff))
* **streams:** drop unknown frames without closing connections ([f95aba1](https://github.com/Polymarket/py-sdk/commit/f95aba1e622fa88aa2bba0583cb103629c6458c0))


### Bug Fixes

* **orders:** reject prices that are not a multiple of the tick size ([2578124](https://github.com/Polymarket/py-sdk/commit/2578124167c4768a546dc4a5d1a511c1762ee626))
* **orders:** reject prices that are not a multiple of the tick size ([87bc4c9](https://github.com/Polymarket/py-sdk/commit/87bc4c9962833cf5fc9c95bca7a538bc4906b578))

## [0.1.0-b21](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b20...polymarket-client-v0.1.0-b21) (2026-07-17)


### Bug Fixes

* **relayer:** stop approving retired neg-risk adapter in trading setup ([#179](https://github.com/Polymarket/py-sdk/issues/179)) ([b664047](https://github.com/Polymarket/py-sdk/commit/b66404776a4514a485f6b6fb2bb913c35d8fc4e8))

## [0.1.0-b20](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b19...polymarket-client-v0.1.0-b20) (2026-07-17)


### Bug Fixes

* **clob:** return TokenId-keyed maps from batch price reads ([a61c71f](https://github.com/Polymarket/py-sdk/commit/a61c71f57300acd4e71eb1ceed3a2b984efaa730))
* **clob:** return TokenId-keyed maps from batch price reads ([a3e3baf](https://github.com/Polymarket/py-sdk/commit/a3e3bafab96029cbc5a7d0de9935a6b1412f84a7))
* **models:** treat empty strings as absent for optional stream decimals ([d4a561f](https://github.com/Polymarket/py-sdk/commit/d4a561f6d751ed5bd5e26f4327bcfd45a2b27056))
* **models:** treat empty strings as absent for optional stream decimals ([377d13e](https://github.com/Polymarket/py-sdk/commit/377d13ed6609a870be5801db7b375c9921a9b967))
* **rfq:** drop unreleased QUOTE_VALIDATION_TIMEOUT_INTERNAL error code ([c8f5d48](https://github.com/Polymarket/py-sdk/commit/c8f5d4872062c18a99da7a4074f9b6bc95ec8d89))
* **rfq:** drop unreleased QUOTE_VALIDATION_TIMEOUT_INTERNAL error code ([ce72cf9](https://github.com/Polymarket/py-sdk/commit/ce72cf97503143a3b5ea46e3d7007b35d5787eea))
* **rfq:** keep sessions open for new error codes ([51a2696](https://github.com/Polymarket/py-sdk/commit/51a26962457890527970b97dd64f989f2f4f155b))
* **rfq:** keep sessions open for new error codes ([9c39dcc](https://github.com/Polymarket/py-sdk/commit/9c39dcc7d1259c236648cae00b73458f4fe92e32))
* **rfq:** pass unknown error codes through and model connection loss explicitly ([4c2e93a](https://github.com/Polymarket/py-sdk/commit/4c2e93a53de25bfeb6ef4df8f3c1ed74589754a8))
* **streams:** support batched Perps fill frames ([9be4c4f](https://github.com/Polymarket/py-sdk/commit/9be4c4f3d9df0c050afc805666c7966349c504c7))
* **streams:** support batched Perps fill frames ([5446ea3](https://github.com/Polymarket/py-sdk/commit/5446ea311077d63d82802c65d23c74d63be301b5))
* **streams:** support batched Perps trade frames ([feb18e3](https://github.com/Polymarket/py-sdk/commit/feb18e378efb2f0834347e620def9969094094fb))
* **streams:** support batched Perps trade frames ([f088ffb](https://github.com/Polymarket/py-sdk/commit/f088ffb1812a974fb641f50bc7ed08b3eb0c30ae))

## [0.1.0-b19](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b18...polymarket-client-v0.1.0-b19) (2026-07-13)


### Bug Fixes

* **models:** add RESOLVED_PARTIAL to ComboPositionStatus ([9ab11ad](https://github.com/Polymarket/py-sdk/commit/9ab11ad44309f0bb43619281b78f8e586a2dcfb9))
* **models:** add RESOLVED_PARTIAL to ComboPositionStatus ([ae31b28](https://github.com/Polymarket/py-sdk/commit/ae31b28ebd67c6c7d5c23036004856b6113f261c))

## [0.1.0-b18](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b17...polymarket-client-v0.1.0-b18) (2026-07-10)


### Bug Fixes

* **models:** parse Combo activity type ([dd606ac](https://github.com/Polymarket/py-sdk/commit/dd606ac7e6b0435a19cac93c073efb9b24c0ecb6))
* **models:** parse Combo activity type ([92ef685](https://github.com/Polymarket/py-sdk/commit/92ef685fc130108d27c6f9e6947875d3bb5e79a8))
* **ws:** bound websocket close latency ([dadc671](https://github.com/Polymarket/py-sdk/commit/dadc671b3a0002acab54856afd00bf1a4921501c))
* **ws:** bound websocket close latency ([0ea0808](https://github.com/Polymarket/py-sdk/commit/0ea08081fa28c77f2365e6765042682db9b4c429))

## [0.1.0-b17](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b16...polymarket-client-v0.1.0-b17) (2026-07-10)


### Features

* **client:** add combo data pagination ([27a4ed6](https://github.com/Polymarket/py-sdk/commit/27a4ed682811dceb287196d7a8745637362940f0))
* **client:** add combo data pagination ([e8e7269](https://github.com/Polymarket/py-sdk/commit/e8e726937ad7c50ac704afb2f6cb304106238ce8))
* **clients:** add typed overloads for market/event/tag lookups ([5189151](https://github.com/Polymarket/py-sdk/commit/51891514cefc759a7f7735145b983226eca989af))
* **clients:** add typed overloads for mutually-exclusive lookup args ([93252f3](https://github.com/Polymarket/py-sdk/commit/93252f3ec121945a156967dd81e1d13cdd6185aa))
* **clients:** add typed overloads for redeem_positions ([7d77862](https://github.com/Polymarket/py-sdk/commit/7d77862c3732fdfb2c182b9e72655b6892734e90))


### Bug Fixes

* **client:** add trade time filters ([6d26ab4](https://github.com/Polymarket/py-sdk/commit/6d26ab4ae0a81ff6aba51c2445eded54c9700e98))
* **client:** harden combo pagination filters ([c37f6ca](https://github.com/Polymarket/py-sdk/commit/c37f6caf87c6c14d566309c253d075a1707e7864))
* **client:** normalize combo data field names ([7727ae5](https://github.com/Polymarket/py-sdk/commit/7727ae565789f9859186987da80cf6c961205f1d))
* **models:** brand combo activity ids ([7de9aa5](https://github.com/Polymarket/py-sdk/commit/7de9aa57b043bbccfae14dd5d081b5f24c1b131a))
* **models:** brand combo activity ids ([b58323e](https://github.com/Polymarket/py-sdk/commit/b58323ede883f058e33bb2c32fcbc00625c41194))

## [0.1.0-b16](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b15...polymarket-client-v0.1.0-b16) (2026-07-08)


### Bug Fixes

* **client:** update auto-redeem operator ([cb709e2](https://github.com/Polymarket/py-sdk/commit/cb709e2bd6044ffe7b9907211d7c5d5c13d50f5c))
* **client:** update auto-redeem operator ([5f7d828](https://github.com/Polymarket/py-sdk/commit/5f7d8283b40857e936474d1e00275e8428af5ea4))

## [0.1.0-b15](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b14...polymarket-client-v0.1.0-b15) (2026-07-07)


### Features

* **client:** add perps support ([9054e7a](https://github.com/Polymarket/py-sdk/commit/9054e7ae5538434f73619c4cded03d6cf985de21))

## [0.1.0-b14](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b13...polymarket-client-v0.1.0-b14) (2026-07-07)


### Features

* **auth:** add builder-api-key management (create/fetch/revoke) ([8f0925e](https://github.com/Polymarket/py-sdk/commit/8f0925ef99700c00f20700de325707319e9fd5ba))
* **client:** support for multiple position merges ([24b8689](https://github.com/Polymarket/py-sdk/commit/24b86895969964bc40425262547e45054f7417e7))
* **examples:** add runnable Python SDK examples ([9d87d2f](https://github.com/Polymarket/py-sdk/commit/9d87d2f813d6034ce27149d55ac69d4c81d996d9))


### Bug Fixes

* **client:** resolve closed markets for redeem ([58fc121](https://github.com/Polymarket/py-sdk/commit/58fc12112d0d45d40a53294360810195408f5fc0))
* **client:** resolve closed markets for redeem ([205f989](https://github.com/Polymarket/py-sdk/commit/205f989b2aad6583edf3fb38ba110568ad67f79c))
* wait for confirmed gasless transactions ([8d02ec1](https://github.com/Polymarket/py-sdk/commit/8d02ec1cf0b6fe3e2a82128a8839bd5a8190d55b))
* wait for confirmed gasless transactions ([2fab25f](https://github.com/Polymarket/py-sdk/commit/2fab25f869de0a97cc55e48bc1f7b63c6f3b6405))


### Documentation

* clarify integration test fixture guidance ([ad8d23c](https://github.com/Polymarket/py-sdk/commit/ad8d23c1b98520f9e3c43916f69b54e44d17a891))

## [0.1.0-b13](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b12...polymarket-client-v0.1.0-b13) (2026-07-03)


### Bug Fixes

* **client:** require 3 minute GTD expirations ([d487124](https://github.com/Polymarket/py-sdk/commit/d4871249fa7f953c43edef18fa80d1e7bd07a8e1))
* **client:** require 3 minute GTD expirations ([0c113cd](https://github.com/Polymarket/py-sdk/commit/0c113cde698b7b5cfbc1c6162b2d534fda5e436a))

## [0.1.0-b12](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b11...polymarket-client-v0.1.0-b12) (2026-07-02)


### Bug Fixes

* **client:** support new clob tick sizes ([a45aa1e](https://github.com/Polymarket/py-sdk/commit/a45aa1ecfaec242d85bf6b194d684d975bfa8f9a))
* **client:** support new CLOB tick sizes ([7e1bb17](https://github.com/Polymarket/py-sdk/commit/7e1bb1763c5165bf366d7351548dc59fbbd7790a))

## [0.1.0-b11](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b10...polymarket-client-v0.1.0-b11) (2026-06-29)


### Bug Fixes

* **client:** clean up deposit wallet deployment ([4140f72](https://github.com/Polymarket/py-sdk/commit/4140f723debabc218c88c8998d3240bf3972e441))
* **client:** clean up deposit wallet deployment ([c098c9b](https://github.com/Polymarket/py-sdk/commit/c098c9bc0eb8ef34522f99b0dcbec92e84b1a4db))
* **client:** split rejected RPC batches ([245b97a](https://github.com/Polymarket/py-sdk/commit/245b97a8147697db178ebe84941f80ccf7475849))
* **gamma:** type search sort fields ([238811a](https://github.com/Polymarket/py-sdk/commit/238811a540167298572c305f676bbfe2205af23e))

## [0.1.0-b10](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b9...polymarket-client-v0.1.0-b10) (2026-06-23)


### Bug Fixes

* **gamma:** preserve market group item title ([e4b8185](https://github.com/Polymarket/py-sdk/commit/e4b81854001d50d1db290f8701fb830ab7d0c17c))
* **gamma:** preserve market group item title ([264ef60](https://github.com/Polymarket/py-sdk/commit/264ef6068aae49f69dfb9f826ede1f2b5ade58cb))

## [0.1.0-b9](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b8...polymarket-client-v0.1.0-b9) (2026-06-19)


### Features

* **rfq:** expose confirmed trade broadcasts ([62f040a](https://github.com/Polymarket/py-sdk/commit/62f040afbcd5030f65d72960a40afe11fcb4ca41))
* **rfq:** expose confirmed trade broadcasts ([7c91ac8](https://github.com/Polymarket/py-sdk/commit/7c91ac89a0e5a0d05ec0ee8a86c0ab1ad6b09fd7))
* **rfq:** expose error ids ([c907fc6](https://github.com/Polymarket/py-sdk/commit/c907fc692a8bae9e970a96b5ec101e26e20e3b61))
* **rfq:** expose RFQ error IDs ([a537547](https://github.com/Polymarket/py-sdk/commit/a53754752e6bd802fef5f00ba537c78f2b0c6e2c))

## [0.1.0-b8](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b7...polymarket-client-v0.1.0-b8) (2026-06-17)


### Features

* **client:** support protected market orders ([f68cd62](https://github.com/Polymarket/py-sdk/commit/f68cd62ab0d71b8e4b234e644f226acbefd6cccf))
* **client:** support protected market orders ([34422bb](https://github.com/Polymarket/py-sdk/commit/34422bbc9d3c40e4941f5dcfa528b94d1080b7c4))
* **models:** add parent_event_id to Event ([4b87156](https://github.com/Polymarket/py-sdk/commit/4b87156ad42daafcef5a84febcb7c3a437d9052d))
* **models:** add parent_event_id to Event ([c966aec](https://github.com/Polymarket/py-sdk/commit/c966aec4368d6f037869385b79efac5c209d48fb))
* **rfq:** support confirmed trade broadcasts ([f55b613](https://github.com/Polymarket/py-sdk/commit/f55b613836e6dd7841f238d72653e90d4db66a16))
* **rfq:** support confirmed trade broadcasts ([a4ba05b](https://github.com/Polymarket/py-sdk/commit/a4ba05b249cbbff4f22b27e45cd4d1645aaa89f8))


### Bug Fixes

* **data:** parse combo trade activity ([24d3cf2](https://github.com/Polymarket/py-sdk/commit/24d3cf2b81447a61af5899e8d742d9b04fbee545))
* **data:** parse combo trade activity ([dc9150a](https://github.com/Polymarket/py-sdk/commit/dc9150aa9c7377725038994eb29fedf53a2fcc39))
* **gamma:** omit legacy non-binary market listings ([f649c6c](https://github.com/Polymarket/py-sdk/commit/f649c6cb3d065f43efbf258a6a02aff79befd9a0))
* **gamma:** omit legacy non-binary market listings ([abbce8c](https://github.com/Polymarket/py-sdk/commit/abbce8c3437e08d82b303baa19ad3fc9237b544b))
* **models:** expose missing activity market icons as None ([0adfad7](https://github.com/Polymarket/py-sdk/commit/0adfad74041b27ea9d4f84f34c9d13dec000244f))
* **models:** expose missing activity market icons as None ([b36b41f](https://github.com/Polymarket/py-sdk/commit/b36b41f1c77a846804ac468bc8301550736a1188))
* **models:** normalize empty-string trade and position icons to None ([233cb2d](https://github.com/Polymarket/py-sdk/commit/233cb2dbb3f40b3f7527c7827e9fc23c942b78ab))
* **models:** normalize empty-string trade and position icons to None ([5949925](https://github.com/Polymarket/py-sdk/commit/5949925393bb72260a86013c2cf1f37d5201421f))
* omit user stream market filter for all markets ([1718ece](https://github.com/Polymarket/py-sdk/commit/1718eceb7d981c6ede8dd5daba924040a10daa48))
* omit user stream market filter for all markets ([65f3ece](https://github.com/Polymarket/py-sdk/commit/65f3ece018800da5f245dd5bc400e1920718ef40))
* **rfq:** support balance error codes ([59e366d](https://github.com/Polymarket/py-sdk/commit/59e366d5ca917d5bd56046140d28c0423d933858))
* **rfq:** support balance error codes ([0a0387e](https://github.com/Polymarket/py-sdk/commit/0a0387ec735d244e4787cc53a26013bfedabf358))


### Reverts

* **rfq:** remove confirmed trade broadcasts ([b5315cd](https://github.com/Polymarket/py-sdk/commit/b5315cdff76962f9711e15fabc1ab16f70508835))

## [0.1.0-b7](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b6...polymarket-client-v0.1.0-b7) (2026-06-10)


### Bug Fixes

* **client:** point Combos RFQ endpoints at polymarket.com domains ([41d511b](https://github.com/Polymarket/py-sdk/commit/41d511be85973f9bff686978de1ddb1a51055985))

## [0.1.0-b6](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b5...polymarket-client-v0.1.0-b6) (2026-06-10)


### Features

* **client:** add combo market catalog ([10bdf99](https://github.com/Polymarket/py-sdk/commit/10bdf9954c2d57ddc27fa73da8a6bf5bb19eb196))
* **client:** add combo market catalog ([3839713](https://github.com/Polymarket/py-sdk/commit/38397138fc30c237d086d2fe277a357b4c2e9f20))


### Bug Fixes

* **rfq:** parse submission window rejections ([f101d69](https://github.com/Polymarket/py-sdk/commit/f101d69d903685b86f1dfa97707bc202c4bdaa8b))
* **rfq:** parse submission window rejections ([ba1b8e9](https://github.com/Polymarket/py-sdk/commit/ba1b8e94ea24b20c4405806bfdf1c1edfa062e49))

## [0.1.0-b5](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b4...polymarket-client-v0.1.0-b5) (2026-06-09)


### Features

* **client:** support combo position lifecycle ([947efd2](https://github.com/Polymarket/py-sdk/commit/947efd2a418bd543c554b160ea25ee99a0774d2d))
* **gamma:** expose market position ids ([cb6a97d](https://github.com/Polymarket/py-sdk/commit/cb6a97d256d6e9b90e0989ef545e54d50b52480c))
* **jupyter:** notebook-friendly models ([8ee5fd3](https://github.com/Polymarket/py-sdk/commit/8ee5fd3cddbe85014c349c6801143260ac3c4141))
* **jupyter:** notebook-friendly models ([02e8574](https://github.com/Polymarket/py-sdk/commit/02e8574d470d4a8ef1fe71e664901aab3601540c))
* **rfq:** add async RFQ session ([7beaafd](https://github.com/Polymarket/py-sdk/commit/7beaafd4e454611dfad613dd9fd29a215202b3a3))
* **rfq:** distinguish combo condition ids ([9ee5b63](https://github.com/Polymarket/py-sdk/commit/9ee5b6305719d9ca5632a5f3eaa947b5c73cd1b0))


### Bug Fixes

* **client:** align market lifecycle context ([d28c211](https://github.com/Polymarket/py-sdk/commit/d28c2117bff70beebccf27582438114fde21d8a9))
* **client:** resolve market ids before redemption ([fa4fe35](https://github.com/Polymarket/py-sdk/commit/fa4fe35741d62583efbabfc422892343c41287c3))
* **clob:** align order book timestamp validation ([4be6456](https://github.com/Polymarket/py-sdk/commit/4be645646fdc41ae8661c00a9a67e0422f708b7d))
* **data:** accept global open interest rows ([1cfda2d](https://github.com/Polymarket/py-sdk/commit/1cfda2ddb0eed8bdcec94eb2023b6514735512b1))
* **data:** accept global open interest rows ([1855b7f](https://github.com/Polymarket/py-sdk/commit/1855b7f2134c4cbb041de4df78d31eb1b9fb0bf4))
* **models:** prefer ctf condition id brand ([59dbe47](https://github.com/Polymarket/py-sdk/commit/59dbe474efbdfd9b1982f7989b24f90cf9bd085d))
* **models:** validate condition ids at runtime ([7a0675d](https://github.com/Polymarket/py-sdk/commit/7a0675dded1a8d1656ee5b5d83f98f9adaf9ea93))
* **rfq:** queue duplicate pending acknowledgements ([c90fdd7](https://github.com/Polymarket/py-sdk/commit/c90fdd7dc156cc9e870f0c68a82a4d0fc477b109))
* **rfq:** use production quoter websocket ([e3f3d27](https://github.com/Polymarket/py-sdk/commit/e3f3d278164869d2916490bf69b4a9718733c40a))
* **rfq:** validate unsupported error codes ([f3a400f](https://github.com/Polymarket/py-sdk/commit/f3a400f2e893eee9b60c6fca785b87ca3004a5b8))


### Documentation

* fix stale items() reference in list_builder_trades docstring ([ad2725c](https://github.com/Polymarket/py-sdk/commit/ad2725c2dbb006efcf360d4dc6f60d5a62b8601f))

## [0.1.0-b4](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b3...polymarket-client-v0.1.0-b4) (2026-06-08)


### Features

* **client:** default secure clients to deposit wallet ([98ad0e9](https://github.com/Polymarket/py-sdk/commit/98ad0e995ef917d372cd025a66bccd9f59c852f4))
* **client:** default secure clients to deposit wallet ([872c5de](https://github.com/Polymarket/py-sdk/commit/872c5ded24be3cecc344492d8a01063787747d56))
* **frames:** add dataframe conversion foundation ([6d873f9](https://github.com/Polymarket/py-sdk/commit/6d873f95b0846a8694a29450bc9673ba4d70556f))
* **frames:** add dataframe conversion foundation ([e17d5bb](https://github.com/Polymarket/py-sdk/commit/e17d5bbcf08f4f6c8db12f715cefd814d8cf1c5d))


### Bug Fixes

* **frames:** emit identity columns for OrderBook sequences ([a4a9601](https://github.com/Polymarket/py-sdk/commit/a4a9601820810fbbf0f159afdc1ccf9b0c1084b3))
* **gamma:** accept event market URLs ([afcdca5](https://github.com/Polymarket/py-sdk/commit/afcdca59f1b2586c0eb235b96977427eabd203a4))
* **gamma:** accept event market URLs ([c1e9893](https://github.com/Polymarket/py-sdk/commit/c1e9893e8f35a603d2166f9bcdaa19c95bcaae10))
* **gamma:** default list_events to open events ([4f66139](https://github.com/Polymarket/py-sdk/commit/4f66139f289733ef4fdf814aac7635b03d7bbd7e))
* **gamma:** default list_events to open events ([9d92d4f](https://github.com/Polymarket/py-sdk/commit/9d92d4f0d11d8ef6af901bbaea0c145082cc712c))
* **gamma:** drop tag/series request params not honored upstream ([0e6c8f0](https://github.com/Polymarket/py-sdk/commit/0e6c8f0d11c21f93b9355b3f28623591481b37f2))
* **gamma:** drop tag/series response fields not populated upstream ([24ff6f9](https://github.com/Polymarket/py-sdk/commit/24ff6f9ce20f53b46c2e84083739ab9b8ee5bf57))
* **orders:** map unknown builder code to user input error ([67a00fb](https://github.com/Polymarket/py-sdk/commit/67a00fb3cf57b42c94ecd3d638d9104b6405930d))
* **orders:** map unknown builder code to user input error ([6cace4f](https://github.com/Polymarket/py-sdk/commit/6cace4fa7e28853d21b287eea9a2168a862bc02b))
* **pagination:** skip fetch when paginator drain limit is 0 ([8ae911c](https://github.com/Polymarket/py-sdk/commit/8ae911cafe18605b219f835a1367ebf8a42bc97d))


### Performance Improvements

* **pagination:** avoid extra fetch when drain limit hits page boundary ([ff38c8f](https://github.com/Polymarket/py-sdk/commit/ff38c8f3c05177b8a1673fcdf3dc8a81f7638970))


### Documentation

* fix get_market examples ([86c6606](https://github.com/Polymarket/py-sdk/commit/86c660685e9231bfa52d4e089e4d4a743f9f2f0f))
* fix get_market examples ([4c893c9](https://github.com/Polymarket/py-sdk/commit/4c893c9327e2b89a8c3c5e52d30f888c9b80e748))

## [0.1.0-b3](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b2...polymarket-client-v0.1.0-b3) (2026-05-26)


### Bug Fixes

* accept GTD expiration boundary ([3a5615f](https://github.com/Polymarket/py-sdk/commit/3a5615f279058df1ba98b77948a03ff13f0be4ab))
* accept GTD expiration boundary ([7d24c67](https://github.com/Polymarket/py-sdk/commit/7d24c67db78311d0307a56f82cc3583b5c79e17f))


### Documentation

* clarify market stream and orderbook fields ([ae23142](https://github.com/Polymarket/py-sdk/commit/ae23142e4bda6587a78433d98985a58aaaa6fdec))
* clarify market stream and orderbook fields ([cb5fc33](https://github.com/Polymarket/py-sdk/commit/cb5fc337715840e06bda436c3777b10cad0819c2))
* note GTD expiration buffer ([20c9600](https://github.com/Polymarket/py-sdk/commit/20c9600c40fe7420a2ed20da993c357db28abf56))

## [0.1.0-b2](https://github.com/Polymarket/py-sdk/compare/polymarket-client-v0.1.0-b1...polymarket-client-v0.1.0-b2) (2026-05-25)


### Bug Fixes

* hide credential validation test switch ([87af5eb](https://github.com/Polymarket/py-sdk/commit/87af5eb7dfc11b07b0abbf20d97d81a0e5e8fb2d))
* hide credential validation test switch ([3cd361a](https://github.com/Polymarket/py-sdk/commit/3cd361a47bb36e4c8415cc2552941fc25a155ede))
* update idna lockfile dependency ([60a1139](https://github.com/Polymarket/py-sdk/commit/60a11392da9950c0a6f02dd4dab6b34512c4ccdb))
* update idna lockfile dependency ([24ca1db](https://github.com/Polymarket/py-sdk/commit/24ca1db9d6654bec32ab03266dcf2a430a8221f9))


### Documentation

* add beta status badge ([1b5baf7](https://github.com/Polymarket/py-sdk/commit/1b5baf71484df9325a9184cce4ef6b7114b77908))
* add beta status badge ([8b4f99b](https://github.com/Polymarket/py-sdk/commit/8b4f99bc297b70bcee3196bc9ee860b7a732c3a5))
* complete public client docstrings ([9b1b28c](https://github.com/Polymarket/py-sdk/commit/9b1b28c0da10963cce987711379840189ff2cd47))
* improve Python SDK public docstrings ([70304f5](https://github.com/Polymarket/py-sdk/commit/70304f56aa7c105147bb4606652c1fa238ea2d3d))
* improve Python SDK public docstrings ([d9d51d1](https://github.com/Polymarket/py-sdk/commit/d9d51d1a1dc32cbb6e2eabb78e5d51f99b464413))
* polish public beta guidance ([f5185a9](https://github.com/Polymarket/py-sdk/commit/f5185a9bea7ce9de71b224093329d980d11130f8))
* polish repo for public beta ([c65142e](https://github.com/Polymarket/py-sdk/commit/c65142e9fb36b5d349d39e41890f0554349c6662))
* refresh SDK direction wording ([59c361d](https://github.com/Polymarket/py-sdk/commit/59c361d2fb2d102c87b52633f3ad6c2de013310c))

## Changelog

All notable changes to this project will be documented in this file.

This project uses Conventional Commits and release-please for release automation.
