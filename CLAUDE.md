# CLAUDE.md -- vivijure-blender

## Role

RunPod **finish satellite**: headless Blender compositor for Vivijure. Paired CF module:
`vivijure-cf/modules/finish-blender` (`MODULE_FINISH_BLENDER`).

## Non-goals (v1)

- User bpy / arbitrary scripts
- Replacing video-finish (ffmpeg assemble)
- Default motion.backend
- EEVEE-as-primary (compositor path; Cycles later for titles)

## Layout

| Path | Purpose |
| --- | --- |
| `handler.py` | RunPod serverless entry; R2/presign IO; ffmpeg extract/encode |
| `scripts/composite_job.py` | bpy template graph (presets only) |
| `Dockerfile` | Blender LTS + handler |
| `Dockerfile.serve`, `serve.py`, `runpod_http_serve.py` | Resident `/run` door on the same image. `BLENDER_IMAGE` has no default. |
| `cf-container/` | Cloudflare Container door (`name = "vivijure-blender"`, route `blender.skyphusion.org`). Not the studio Worker. Image is `Dockerfile.cf`. |
| `deploy.sh` | build/push/endpoint |

## Version

Released changelog line is **0.2.2** (`CHANGELOG.md`); the top section is **Unreleased**. A `vX.Y.Z` tag must match a `## X.Y.Z` heading: `.github/workflows/deploy.yml` refuses to deploy a tag the changelog does not declare (`scripts/deploy_gate.py`). Bump CHANGELOG and the tag together. Do not treat 0.1.1 as the current line.

## Release convention (bump-at-release)

One convention for every skyphusion-labs repo (Conrad, ruled 2026-11-10, fleet-chezmoi#1766). A version moves ONLY in a release PR: bump the version, then assemble the changelog. Feature and fix PRs do not bump. Releases go through a PR (fleet-chezmoi#1622) and the tag goes on that PR's merge commit.

- Version of record here: no manifest version: the git tag and the CHANGELOG heading are the version of record.
- Tag shape: `v*`.
- Check before a release PR: does a tag already exist for the version currently in the manifest? Yes means the cycle is closed, so the release PR bumps. No means a bump already landed outside a release PR; stop and read why before bumping again.
