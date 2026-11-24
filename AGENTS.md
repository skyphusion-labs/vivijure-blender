# Vivijure Blender

This file is the guide for any coding agent and any contributor. Follow it.

## What this project is

This repo is a finish satellite for Vivijure. It is a headless Blender compositor. It runs on RunPod Serverless, or as a Cloudflare Container door.

The paired module is `vivijure-cf/modules/finish-blender` (`MODULE_FINISH_BLENDER`).

Read [README.md](README.md) and [docs/constellation.md](docs/constellation.md). Presets grade a shot clip. The graph is baked. There is no free-form user script.

## Non-goals

- No user bpy and no arbitrary scripts.
- This door does not replace video-finish (ffmpeg assemble).
- It is not the default motion backend.
- The compositor path comes first. EEVEE is not the primary path. Cycles for titles can come later.

## Layout

| Path | Purpose |
| --- | --- |
| `handler.py` | RunPod entry; R2 or presign IO; ffmpeg extract and encode |
| `scripts/composite_job.py` | bpy template graph (presets only) |
| `Dockerfile` | Blender LTS plus the handler |
| `Dockerfile.serve`, `serve.py`, `runpod_http_serve.py` | Resident `/run` door. `BLENDER_IMAGE` has no default. |
| `cf-container/` | Cloudflare Container door (`name = "vivijure-blender"`). Image is `Dockerfile.cf`. It is not the studio Worker. |
| `deploy.sh` | Build, push, and endpoint helper |

## Commands

CI is `.github/workflows/ci.yml`.

```bash
ruff check --select E9,F .
python -m py_compile handler.py scripts/composite_job.py
pytest -q
```

The same workflow also runs `npm test` in `cf-container/`. Install Python deps from `requirements.txt` plus pytest before `pytest`. See the workflow for the exact steps.

Image publish is `.github/workflows/build-image.yml`. The container deploy workflow is `.github/workflows/deploy.yml`. Read [docs/deploy.md](docs/deploy.md).

## Release

See [CHANGELOG.md](CHANGELOG.md) for the released line. The top section may be Unreleased. Do not treat an older heading as current.

A `vX.Y.Z` tag must match a `## X.Y.Z` heading. `.github/workflows/deploy.yml` refuses a tag the changelog does not declare (`scripts/deploy_gate.py`). Bump the changelog and the tag together.

A version moves only in a release pull request. A feature pull request does not bump. A fix pull request does not bump.

There is no package manifest version. The git tag and the changelog heading are the version of record. The tag shape is `v*`.

Before a release pull request, check tags. If the current changelog version already has a tag, the cycle is closed, so the release pull request bumps. If it has no tag, stop. Read why before you bump again.

An org admin tags the release pull request merge commit. A merge to `main` is not by itself a production pin. Do not freeze an endpoint id in this file.

Use a Conventional Commit. The body says why.

## Docs language and safety

Write Simplified Technical English. Use short sentences. Put one idea in each sentence. Use the active present tense. Use plain words. Use the same word every time.

Do not use an em dash (U+2014). Do not use an en dash (U+2013). Use a comma, a semicolon, parentheses, or two hyphens (`--`).

State the limit next to the capability. Do not turn a measured result into a promise.

Do not put a secret in a tracked file. Do not put a secret in a log. Do not put a secret in an issue.

Blender is GPL. Keep that license visible when you change the image. See [README.md](README.md).
