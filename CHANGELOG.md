# Changelog

## [0.3.6](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.3.5...v0.3.6) (2026-09-01)


### Features

* add safe UE 5.8 Niagara authoring ([e2fc80c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/e2fc80cdedc29a9684283c8835ad642675d6cc6e))

## [0.3.5](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.3.4...v0.3.5) (2026-08-31)


### Features

* add verified customized uv connections ([fbc5bc9](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/fbc5bc960fb02c841c300f8b2c6c4284e2b887d0))
* add verified material instance parameters ([38189af](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/38189af7460ba7b7f3f92606275d0ff90080d09b))


### Bug Fixes

* bind install payload to target distribution ([01cc703](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/01cc7031919237f8e76a90f9a63d93cf400579ca))
* harden install transaction ownership ([5231e1c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5231e1c5bfff3076366a4bd98c43f28569cd9b68))
* harden material instance verification ([002eae5](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/002eae58ce878f4fccdce1f0e18f5896bfd374d9))
* isolate target ownership probe ([bd8fa87](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/bd8fa87026774a2f4648629a904ca43749d48a8d))
* make PIE log snapshots queryable ([#201](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/201)) ([25438f4](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/25438f4bfb601b65bda2146a2634b80a2d5683d7))
* make Unreal diagnostics retry-safe ([4268466](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4268466945eb163a0350bd36d6600fd93b990b5d))
* **playtest:** bind input cleanup to native receivers ([b2e4f21](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b2e4f21ff9099175be84d881a78d92ce175ade38))
* **playtest:** bind navigation and recovery lifecycles ([9c079dd](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/9c079dd670e5f3dbb06f493583f84218a3af3f4b))
* **playtest:** guarantee bounded key release ([33ce631](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/33ce6315894b80d1774df7e711607978fcd50685))
* preserve install ownership across package contexts ([d1eec31](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d1eec31aa4f7a2d3b6673b9c3e6a41dc71f11adf))
* support embedded Python ownership probes ([e0acb83](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/e0acb83f89a8a36c4968678f79dd095ad5045209))
* support material bridge on unreal 4.18 ([582d1b5](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/582d1b5b95e6125f9a4ac43b0386894bca989de3))
* verify playtest movement transitions ([e5665e8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/e5665e837b75ba7d9d7d7af4050581ee888afdad))

## [0.3.4](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.3.3...v0.3.4) (2026-08-26)


### Features

* add reusable playtest combat telemetry ([#190](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/190)) ([4d4272c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4d4272c159f79ae19c53262766ec737b6c6806f7))


### Bug Fixes

* unify PIE session actor resolution ([f7da9e1](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/f7da9e1e9ab390fb99c55de20a7f0eae53fc2e34))
* verify project mutation postconditions ([a028b91](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a028b910580499086e5e88aaa9e15f4ceb68759f))

## [0.3.3](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.3.2...v0.3.3) (2026-08-25)


### Features

* add structured PIE playtest agent ([#188](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/188)) ([6d2dc80](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6d2dc801de4b1a9f940ae4561914c2c601e29a71))


### Bug Fixes

* make PIE look input deterministic ([9177009](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/917700963f6c5866d152985997aec605941712d4))

## [0.3.2](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.3.1...v0.3.2) (2026-08-24)


### Bug Fixes

* support PIE menu input ([94ccbd8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/94ccbd8a6b1f75e26c5912c2a05f0f5e75ed4916))
* support positioned PIE menu clicks ([#184](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/184)) ([4fd5031](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4fd5031f56ff3ac2b89324edf63c5801505ae9b3))

## [0.3.1](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.3.0...v0.3.1) (2026-08-24)


### Features

* add Unreal install lifecycle ([b4a7cc7](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b4a7cc76aba75a4130636963f10706021faa68a7))
* add Unreal plugin preflight ([a5d9c6a](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a5d9c6aaa4cd81a8884d7e341e4a74591eab1d6f))
* **unreal-assets:** add typed static Groom import ([#167](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/167)) ([63fa7e8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/63fa7e8581f609e9f8782599d29f22b85112a45e))
* **unreal-assets:** expose Groom topology counts ([#162](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/162)) ([5f0077d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5f0077da33a79e1edacb8e75360313ffc6a33a1a))
* **unreal-assets:** safely import versioned groom caches ([#164](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/164)) ([15b5da0](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/15b5da0bd9f955c3d52d4a275336f045139256e5))
* **unreal-hair:** add typed Groom Cache binding ([#168](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/168)) ([1f49336](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1f4933690958a8df5a6efc047401cc56c3295765))
* **unreal-umg:** add UMG Widget Blueprint authoring skill ([16a7a49](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/16a7a493062beb3705f1f3ade83c5a7cb90f21c7))


### Bug Fixes

* harden Unreal install lifecycle ([5c34433](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5c34433991a0a8524182bdf53f6d94accdbc21c2))
* inject PIE input through player controller ([#178](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/178)) ([e71cefb](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/e71cefbc8a904cc709a0321f27b9b3fd90ece0ea))
* keep PIE screenshot capture non-blocking ([#176](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/176)) ([e2fa278](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/e2fa278311eaf7529b8126d2b27e5994596c73be))
* pass valid PIE screenshot command ([#180](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/180)) ([f769e1d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/f769e1d242d9504812e1a9607d5230fd736ce35c))
* **pie:** expose screenshot artifact readiness ([#170](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/170)) ([6c9811e](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6c9811ee78877fcc5a67a5eaf659952a10b3bfcf))
* **pie:** keep jobs across isolated script loads ([#171](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/171)) ([980713d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/980713dd388efefae42f85cd2770d32dd3acef85))
* resolve Unreal plugin root without file globals ([#177](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/177)) ([90d7c33](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/90d7c33ad52f139a8ad85f4bca8f1bbea403b557))

## [0.3.0](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.17...v0.3.0) (2026-08-12)


### ⚠ BREAKING CHANGES

* migrate UI Control to dcc-cua 0.4.0 ([#157](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/157))

### Features

* migrate UI Control to dcc-cua 0.4.0 ([#157](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/157)) ([2f8701b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2f8701bbabe538475c54e6289b1ef8fd70027757))


### Bug Fixes

* tolerate stale UE 5.8 generated headers ([4acc002](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4acc002fb475230c02a20a8688971f29561c8ef5))

## [0.2.17](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.16...v0.2.17) (2026-08-04)


### Bug Fixes

* allow explicit 8192 Lumen atlas ([#151](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/151)) ([2e87893](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2e87893caf5eabc5c8f131d24522e1b93e99c339))
* default project config inspection keys ([4eb9589](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4eb9589f112da20ff450b5038d0e910fb8a26597))
* default project config inspection keys ([#152](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/152)) ([d565fa2](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d565fa227eb365b41f9227e7aff1708e3562a7d9))
* parse Unreal project argument ([1fd0d96](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1fd0d96f6329cafdde892fd79cdee2109394d602))
* parse Unreal project argument ([bf7e602](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/bf7e602e37ac7e541fa1199ec92bbaf9288f739b))
* reuse cinematic camera bindings ([67cc872](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/67cc8720d566bf249e27c677a68f5a4de482e2ce))
* reuse cinematic camera bindings ([10d2551](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/10d255168950f40061e93b2927fd681643d4426a))
* support Overture GeoJSON theme hints ([9ccfe77](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/9ccfe779d414b0b396a6ccb62ba6d42f06c98558))

## [0.2.16](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.15...v0.2.16) (2026-08-03)


### Bug Fixes

* cap unsafe Lumen atlas settings ([453a45a](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/453a45a74d9b879cb1d3523db3875d4cb49b697d))
* preflight unsafe Lumen config before MRQ ([7ae80ff](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7ae80ffdc938162878ee2ca4a9213f2c913fa5cf))
* reject stale local core when packaging plugin ([1fee083](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1fee083da781969b1a1d78f95060b09d41b4d8ab))
* tolerate non-editor config preflight ([32af88b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/32af88ba73a84a9fa3ca425a1fe593421553271d))

## [0.2.15](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.14...v0.2.15) (2026-08-03)


### Features

* add Unreal PCG refresh skill ([#141](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/141)) ([d1f32b3](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d1f32b3911bd8d874aaff6740eebdaa5ff5e4a81))


### Bug Fixes

* accept Unreal material asset classes ([93a0607](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/93a060789234166e7933d6b6a97f38fb8a1fe2b2))
* bind Unreal UI control to core contract ([5761a66](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5761a66b1186cb7a10a0e33d4d25e6c69da602b4))
* bind Unreal UI Control to core contract ([f9dbe58](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/f9dbe58a63bf147fb6284dbf3d5ec88c053d0aaf))
* defer Unreal MCP startup until editor tick ([0f9df22](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/0f9df22cf06aedd94764caf947ab4c303499b484))
* preserve PCG refresh execution ([5fb1724](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5fb1724fe0e8d7ee97afef11b15a986904f6b32a))

## [0.2.14](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.13...v0.2.14) (2026-08-02)


### Features

* add safe Unreal project config skill ([#134](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/134)) ([fb3386d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/fb3386d7fe54d41d9e3c0b7246c1a302238968e1))
* harden Unreal MCP skills and blueprint layout ([534b387](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/534b387898c168432a2cdcd47c401af9672d0940))


### Bug Fixes

* avoid Unreal API for config path discovery ([#137](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/137)) ([d880a4d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d880a4d5ec90435a9d35ff94aa3f31a5e7dfcaef))
* ignore unrelated Unreal console variables ([#135](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/135)) ([c73f608](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/c73f608caf629645d89bb8ab8b60d88f0712126a))
* keep private config selection out of public skill ([5f75226](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5f75226fc69bd4bceeb3ec72ae6850b9bc666c35))
* keep showcase details out of public skills ([#136](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/136)) ([2f1dd3a](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2f1dd3a3b6f767992b3bfe568622160ceda4cecd))

## [0.2.13](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.12...v0.2.13) (2026-08-01)


### Features

* add automotive rain film skill ([a807e5f](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a807e5fc94fe10af519027a633e074ab1dbdf1c4))
* auto-layout Unreal Blueprint graphs ([7a97f03](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7a97f038dd13f0b96cd6157459486924367f9c06))


### Bug Fixes

* attach standalone installer to releases ([32f1256](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/32f12561bd4c40f7bf754dc7fbe27dfe6c9be8b0))
* bound official MCP calls by one deadline ([b628fde](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b628fde7c52b2b7a8b226f7f799b9bbdae2f01c6))

## [0.2.12](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.11...v0.2.12) (2026-08-01)


### Features

* add geospatial PCG table importer ([#123](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/123)) ([70415c0](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/70415c0b1394bb88fcedc415783b11fa84616e93))


### Bug Fixes

* propagate official MCP tool errors ([#126](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/126)) ([453202c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/453202c5765e42cf3a2969b2830ba357c1c1e7b9))
* report pending screenshot captures ([#124](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/124)) ([a100c4c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a100c4c2071ef26beaef5d61352a7d67f1cfcd30))

## [0.2.11](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.10...v0.2.11) (2026-08-01)


### Features

* add high-quality turntable rendering ([4918cf5](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4918cf540b017bd00bf7d554c22c5e01750c7eed))
* add ue 4.26 lookdev coverage ([6470622](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/647062202bdd3380f8065ff7c5ff4f6cb245bb96))
* add UE 4.26 native sidecar support ([58986f5](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/58986f5e54385ad71229c05269d4f4b255293c61))
* add Unreal plugin branding ([ee23a7f](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/ee23a7ffc32432561765e5f4940f79023ad5ec94))
* publish live Unreal scene context ([122331d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/122331df6ce305e0765f23be58401156778d6204))


### Bug Fixes

* reuse precompiled UE4 automation tool ([6bca232](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6bca23225af1f682b0a196c1d788374c48411d7a))
* use available Unreal CI installations ([6e7594b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6e7594bf4ea653276ed31492ed5065c52f96f9bc))


### Documentation

* explain DCC MCP scope and refresh README ([07388e0](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/07388e0d9a2076d8467af6a87741b3718e28c5ec))

## [0.2.10](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.9...v0.2.10) (2026-07-28)


### Bug Fixes

* align packaged core requirement ([449ea40](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/449ea405dc39a6ea28187ad019d0a81e0bfa3354))
* bind UI Control to Unreal process ([d7f662b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d7f662b05606b5068ca5640283738e0a40b895e0))
* isolate legacy Unreal toolchain config ([0e56daa](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/0e56daae770ef71922b6d410e033b4e2092321cc))
* migrate Fab skill to UI Control ([1e3eed6](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1e3eed694ab6756a3b69032a5a5208290a2e739c))
* require core with UI Control resume ([397685e](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/397685e73f1cf763a85f95d9e7dfc41f4d55c2aa))
* restore Unreal build coverage ([95aaa12](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/95aaa12d2909485a7d6fb39c41e9fec8df96f9de))
* support UE 5.5 automation filter mask ([a260e9d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a260e9d3cfb3963f0bf4d66e8e5cd9c4a2496b24))

## [0.2.9](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.8...v0.2.9) (2026-07-26)


### Bug Fixes

* use supported UE 5.8 PIE APIs ([#106](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/106)) ([7537bd8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7537bd81606af1102fb66863af80713ca6a44885))

## [0.2.8](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.7...v0.2.8) (2026-07-26)


### Features

* add unreal-pie skill for PIE closed-loop verification ([#97](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/97)) ([7e12792](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7e12792cbefe6b3726e2452115a48d1cc043defa))
* add verified cinematics and Niagara skills ([1d81982](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1d8198219d8fb4eed0d17e8a4102287804348091))
* add verified Unreal MetaSound authoring ([7b7839f](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7b7839f1a80363cfcc4dc8aa3f78fe3889ba8981))
* support Alembic geometry caches ([#105](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/105)) ([5a82f62](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5a82f622616ab367c3a2314e9c119834f71f89bb))


### Bug Fixes

* keep unexecuted PIE tests pending ([#104](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/104)) ([af126ce](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/af126ce38fa24624a575db9e64eebaa4d5fceb72))

## [0.2.7](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.6...v0.2.7) (2026-07-25)


### Features

* add typed chaos destruction workflow ([bd08c7b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/bd08c7bbd69138d4949c53cc8a1d2d0127005ae8))
* add typed Chaos destruction workflow ([8f9d747](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/8f9d7478ff288b9a2a267da0c7bb358c701252bd))

## [0.2.6](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.5...v0.2.6) (2026-07-25)


### Features

* **unreal:** add unified menu with Copy Instance ID, Server Info, and About ([b38a3f3](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b38a3f3b2991074cb37897b1914c89ce72bf1624))


### Bug Fixes

* vendor base core in Unreal plugin ([2368c48](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2368c4877bb57670eed130aec3c6356885741408))

## [0.2.5](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.4...v0.2.5) (2026-07-23)


### Bug Fixes

* guard only UE4 automation config ([#90](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/90)) ([2824ba5](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2824ba5b6280fa2c12ffb110e34d9047736b635b))

## [0.2.4](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.3...v0.2.4) (2026-07-23)


### Bug Fixes

* preserve shared UE build settings ([#88](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/88)) ([2316d8d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2316d8d6de42e63d7304a62d239ebd7a3fee5765))

## [0.2.3](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.2...v0.2.3) (2026-07-23)


### Bug Fixes

* isolate UE4 build configuration ([#86](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/86)) ([2777fa3](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2777fa3f92a4c2d70dafd2e500c7583c6d7fe5aa))

## [0.2.2](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.1...v0.2.2) (2026-07-23)


### Bug Fixes

* isolate UE4 automation logs ([#85](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/85)) ([607bd58](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/607bd58a1c5f42f48723766c7eb0d52b6f274141))
* package UE4 with build Python ([#82](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/82)) ([b97c2eb](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b97c2ebf4356bc6f7a13142c9857ae9dac252efc))
* restore Unreal release packaging ([#80](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/80)) ([108be63](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/108be63103444e94e4ce6bfede192cee2bdf7c30))
* reuse UE4 automation tool binaries ([#83](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/83)) ([0416fb9](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/0416fb9e71f9b63ac4dcdd3e028ae27825151d20))
* select compatible core release assets ([#84](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/84)) ([b8393b6](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b8393b63a430c0bc04a5ce94f6b223dcf8bcb4ad))

## [0.2.1](https://github.com/dcc-mcp/dcc-mcp-unreal/compare/v0.2.0...v0.2.1) (2026-07-23)


### Features

* add game distribution profiles ([5e342f4](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5e342f44f4dd3cd191e32fd65680a13dc81024f6))
* add pythonless standalone installer ([41a4bea](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/41a4beaf292db67a74fa053171fe3d005c3d1bfe))
* add Unreal build and package automation ([95877f6](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/95877f6200010e4e9a7f1ce7941e871cdc77dab5))
* add Unreal Fab asset workflow ([32561c9](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/32561c95235ea0a3ec39a4a6e2f7eaa9532712cc))
* add unreal-blueprints skill with auto-main injection ([f82211b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/f82211b30f28f2d912248ad1772d3843854a8b06))
* add unreal-blueprints skill with auto-main injection ([602038a](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/602038a25e1ee4debedcd3aa6e4b0d716bd62bb9))
* add unreal-blueprints skill with auto-main injection ([#76](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/76)) ([f82211b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/f82211b30f28f2d912248ad1772d3843854a8b06))
* automate authenticated Fab sessions ([#68](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/68)) ([bcee28d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/bcee28d3b395ebdadabaae2812eb57350a893181))
* bridge Unreal official MCP capabilities ([6823bf8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6823bf8ad3c5f174e304f951e8aedd61ce1a9646))
* control Unreal material base color ([b2704ad](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/b2704adfb560c89906171432a070d74fb8c73c5e))
* create Unreal PBR texture materials ([2780941](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/27809412a435f201658ece2cc3828c074dec334f))
* extend native Unreal sidecar support ([7d8a0b0](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7d8a0b0b4a19e755b777235dc0c86c059ac3220e))
* gate Fab assets by visual direction ([68a3201](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/68a3201c3f9dc43ed46934a78141b3a5bd452cb6))
* improve Unreal asset authoring ([49f6df1](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/49f6df1f5c8c76799c33644ef05a51fad8369709))
* prepare Unreal 5.8 official MCP and CI ([d0e4225](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/d0e422537a226c296119249f81d9e3a656a3ba0e))
* support skeletal FBX asset workflows ([88ac42e](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/88ac42e07b90d3b2afb754be300981c28f6b74c1))
* UE 4.18 native bridge with cross-version C++ compatibility ([6b7b43b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/6b7b43b0da560e7cf4260d85ae0af2c77940861d))


### Bug Fixes

* **ci:** reuse verified Unreal plugin builds for releases ([#63](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/63)) ([be9ed25](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/be9ed25ee58ce6a6d3b781f37e59e46f212347bd))
* keep runtime release version in sync ([979e9d0](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/979e9d03b8db25e0521daaf23e6661f3c5a4bb90))
* make app-ui test platform-aware ([5e5228f](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5e5228f58ef315248c4db699de14dff83ad481b5))
* require Python 3.10 or newer ([1f6057c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/1f6057cb0407c3ac92a5f18586ce6ce23f1596ab))
* resolve ruff lint errors (F821, F841, F541, I001) ([5b52b6c](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/5b52b6c86a6445a41ef32575e07401d72f131e99))
* resolve ruff lint errors in test_skill_runner.py (I001, F401) ([cfce43d](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/cfce43d3129b0971e3868f3f955a039a458765ee))
* ruff format compliance for blueprint and automotive-rain-film scripts ([38614f0](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/38614f09e8c3a83f0ad838404ecba6452a53b230))
* select Unreal runtime without conflicts ([a84252b](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/a84252b0a6ab4a23aa098d5feed3eb82101c6b71))
* select valid compiler for Unreal 5.8 ([43566af](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/43566af6b5b29312463722ae650654826068d2ec))
* stabilize Unreal editor integration ([7068c46](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/7068c46fd2a77cdf6a9f33b636a3176df4ebed8c))
* support Unreal 5.8 asset data paths ([807c133](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/807c1331d0d941b6c014b05ebed43c84f45b0e29))


### Code Refactoring

* auto-discover [@skill](https://github.com/skill)_entry scripts, remove boilerplate from 27 tools ([2c8d1e5](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/2c8d1e5a60b59086c12aaf789204ecaa41c8cf3a))


### Documentation

* align agent workflow and branding ([4844da8](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/4844da84c4e24402a64f6a96c6906f5706850b3f))
* document CLI install and updates ([099cd54](https://github.com/dcc-mcp/dcc-mcp-unreal/commit/099cd54a19cdda7547d4de44823098f57faecd72))

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
