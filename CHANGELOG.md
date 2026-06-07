# Changelog

## [0.2.0](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.1.0...v0.2.0) (2026-06-07)


### Features

* add Unreal Engine uplugin skeleton + layered CI validation ([4cc255e](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4cc255e4b9b098bb601bc85baee9d1252d5f9438))
* align server.py, api.py with dcc-mcp-maya patterns; add capabilities, CI/CD ([cf8ad36](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/cf8ad3685fb1eebca1cd90c96e8b62705639f7e9))
* initial placeholder for dcc-mcp-unreal ([1602379](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1602379394a3f2fc01bda6f488c7a39b5d932e34))
* package Unreal plugin releases ([#4](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/4)) ([5c6260d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5c6260d2988ff277301a28b634820aab67eeed80))
* **skills:** implement unreal-assets and unreal-level skill scripts ([be291de](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/be291dee6e65089880d578da4572bef2698f23cf))


### Bug Fixes

* **ci:** add max-parallel to test matrix to prevent runner exhaustion ([a9510d6](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a9510d6dea3dbb5506dae592721a1418191192b2))
* **ci:** add VitePress docs project to enable docs deployment ([6d250a9](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6d250a9addbb783dcc8a808739b199a785d5a29f))
* **ci:** isolate workflow_dispatch from push concurrency in release workflow ([ff68e24](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/ff68e248a29202f25c5aabad7c45a0978bc58897))
* **ci:** isolate workflow_dispatch from push concurrency in release workflow ([d573f96](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d573f960b082dd2766f0c8029510026549f2dcd6))
* **ci:** remove npm cache config referencing missing docs/package-lock.json ([86fc55d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/86fc55db2f4a66339e6df068a53960b8debda046))
* **ci:** upgrade release-please-action v4 to v5 with safe output handling ([691f649](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/691f64965308c222c84e4ac1b1cf8df811364d67))
* **ci:** use GITHUB_TOKEN for release-please-action ([9b788ba](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/9b788ba7fb11829a0f243f495c15272bedf84d25))
* **ci:** work around dcc-mcp-core 0.18.7 shutdown SIGABRT in conformance test ([36b64f8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/36b64f8687867ee7088637a7468377a63d663305))
* **docs:** add "type": "module" to enable ESM for VitePress ([32a60f6](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/32a60f6796af505b9f9133a94bfc96f8bd2033d7))
* replace stale tool names in MCP conformance CI test ([fc3a891](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/fc3a8911f02217dfbcb491c5f6bd8132ebdbce45))
* replace unicode checkmark with ASCII in post_install.py for Windows cp1252 compatibility ([3810c50](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/3810c503396643e1404e030db72acb13201b0fa0))
* resolve CI issues, complete unreal-actors skills, verify pip packaging ([34f25be](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/34f25beb13c011f040ad9389a2755670845413bb))


### Miscellaneous Chores

* bump dcc-mcp-core dependency to &gt;=0.18.7 ([c6acd3a](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/c6acd3ad6f3ed13de66dfdca38fd21b4879d3100))
* bump dcc-mcp-core dependency to &gt;=0.18.7 ([38232d4](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/38232d4cda92ccffe8f3ae38575d14a26e3ee6b6))


### Tests

* expand test suite to 35 tests covering new API surface ([0a7c960](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/0a7c96030faecdaa720db38567b5a210114d14c7))
