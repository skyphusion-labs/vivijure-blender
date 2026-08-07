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
| `deploy.sh` | build/push/endpoint |

## Version

Image / package narrative: **0.1.1**. Bump CHANGELOG + image tag together.
