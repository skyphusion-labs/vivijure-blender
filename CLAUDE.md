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

Released changelog line is **0.2.0** (`CHANGELOG.md`). Newest git tag is **v0.2.1** (no 0.2.1 heading in the changelog). `main` is ahead of that tag; the top section is **Unreleased**. Bump CHANGELOG and the image tag together. Do not treat 0.1.1 as the current line.
