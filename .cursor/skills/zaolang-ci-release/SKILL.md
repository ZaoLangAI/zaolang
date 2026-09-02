---
name: zaolang-ci-release
description: Engineering delivery chain — local `make check` and pre-commit gates, local Docker images and one-command demo orchestration, manual version bumps, the MkDocs Material docs site, and the internal-proprietary licence baseline. Use when changing pre-commit hooks, Dockerfiles, the release compose file, version numbers, the docs site, or repository/licence baseline files.
disable-model-invocation: true
---

# Local Delivery, Images & Docs Site

## Scope

Guarantee "it builds, it ships, it's documented." This repo is internal-proprietary software. It does not use GitHub Actions, GHCR, release-please, or GitHub Pages. **Single-host remote deploy (rsync, `infra/docker-compose.prod.yml`, migrate, optional DB overwrite) is `zaolang-remote-deploy` — do not duplicate that runbook here.**

## Key Paths

| File | Contents |
| --- | --- |
| `Makefile` | the single gate entry point: `make check`; one-command demo: `make release-up` |
| `.pre-commit-config.yaml` | local hooks: ruff / mypy / prettier / eslint / tsc / messages (i18n keys) / OpenAPI drift, plus the stock pre-commit-hooks (merge-conflict, yaml/json/toml, private-key, large-files ≤512kB) |
| `front/package.json`'s `version` + `APP_VERSION` | bumped by hand at release time; `next.config.ts` exposes it as `NEXT_PUBLIC_APP_VERSION`, the backend reads `settings.app_version` and shows it in `/healthz` and the admin health cards |
| `front/vitest.config.ts` + `src/**/*.test.ts(x)` | frontend unit tests, run via `npm test` in `front/` only — `make test-front` is typecheck + `next build` + bundle-size, and vitest is not part of `make check` |
| `mkdocs.yml` (`strict: true`) + `docs/` | the docs site, embedding `docs/openapi.json` |
| `back/Dockerfile`, `front/Dockerfile`, `infra/docker-compose.release.yml` | local production images and one-command demo orchestration |

## Invariants

1. **The only gate is `make check`.** E2E and accessibility suites need a real database and seed data — they're an extra local suite, not something to fold into `make check` "to be safe" (that would make every commit depend on a full seeded database).
2. **The autouse fake-gateway fixture inside `make check` must not be bypassed**: tests must be deterministic, key-free, and cost-free. Production code has no stub/auto mode — only `back/tests/fake_llm_gateway.py`'s monkeypatch (via `conftest.py`) keeps the suite offline. `@pytest.mark.live` smoke tests never run inside `make check` (`-m "not live"`); `@pytest.mark.real_gateway_seams` tests still run, they just skip the fake to exercise the real client's own failover/circuit-breaker logic against a mocked transport.
3. **The version number lives in two places**: at release time, bump `front/package.json`'s `version` and sync `APP_VERSION`. Don't update only one. `NEXT_PUBLIC_APP_VERSION` is injected at build time but no consumer page renders it — `(site)/layout.tsx` has only `TopBar` + `main`, no footer; the version is visible in admin health (`health-cards.tsx`) and `/healthz`.
4. **Internal-proprietary, not open-source compliance.** This repo's software licence is internal-proprietary (root `LICENSE`). The consumer site has no footer and shows no version, source link or licence notice — **do not** add a source-repo link or an AGPL notice. Third-party NOTICE/LICENSE files (e.g. OpenCut's MIT notice) must not be removed.
5. **`mkdocs.yml` is `strict: true`**: dead links and orphan pages fail the build. Adding a doc means adding it to `nav` too. `docs/performance-audit.md` currently sits outside `nav` (MkDocs only logs INFO for pages missing from `nav`, so strict mode doesn't catch it) — it's unreachable from the site; don't add more like it.
6. **`docs/openapi.json` is a build artifact**: `make docs` / `make docs-build` copy it from `back/openapi.json` — never hand-edit it.
7. **Docker images ship with ffmpeg/ffprobe**: the backend worker's `complete` and `media_analysis` steps depend on ffprobe. `back/Dockerfile` already installs it — don't strip it from the image.
8. **Never reintroduce GitHub-hosted builds**: no new `.github/workflows`, no pushing to GHCR, no release-please, no GitHub Pages deployment. There is no root `.github/`; the only workflow file is vendored upstream (`third_party/opencut-classic/.github/workflows/bun-ci.yml`) and is not ours to wire up.

## Extension Points

- **Add a check**: first decide whether it needs a database. If yes → a separate `make` target, not folded into `make check`. If no → wire it into the existing `make check` / pre-commit.
- **Add a pre-commit hook**: add the hook to `.pre-commit-config.yaml` and confirm `make check` has an equivalent command — the two must match, or `make check` passing locally while the hook still blocks becomes a real annoyance.
- **Change a Dockerfile**: `front` depends on `output: 'standalone'` (already set in `next.config.ts`); `back` installs via pip outside conda to keep the image small. Verify with a local `docker build` or `make release-up`.
- **Add a docs page**: `docs/*.md` + `mkdocs.yml`'s `nav`, then `make docs-build` must pass.

## Verify

```bash
make check          # the full local gate
make docs-build      # strict-mode docs build
make release-up      # build images locally and start the one-command demo orchestration
```
