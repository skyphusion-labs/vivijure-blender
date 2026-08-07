# Deploy vivijure-blender

## Prerequisites

- Docker
- RunPod account + API key
- GHCR (or other registry) login for `IMAGE`
- Same R2 bucket the studio/backend use (finish-chain keys)

## Steps

1. `cp deploy.env.example deploy.env` and set:
   - `RUNPOD_API_KEY`
   - `IMAGE` (e.g. `ghcr.io/<you>/vivijure-blender:0.1.0`)
   - `ENDPOINT_NAME`
   - `GPU_TYPE_IDS`
   - `R2_ENDPOINT_URL`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
2. `./deploy.sh`
3. Copy the printed **endpoint id** into the studio as `BLENDER_RUNPOD_ENDPOINT_ID`.

## Verify

```bash
# After workers warm (or on a one-off pod):
# POST /run  {"input":{"selftest":true}}
```

Expect `{ "ok": true, "applied": ["selftest:grade:filmic_warm"], ... }`.

## Env knobs

| Env | Default | Meaning |
| --- | --- | --- |
| `MAX_FRAMES` | 600 | hard cap on extracted frames |
| `BLENDER_TIMEOUT` | 1800 | seconds for the blender process |
| `FFMPEG_TIMEOUT` | 1200 | extract / encode wall clock |
| `BLENDER_BIN` | `/opt/blender/blender` | override binary path |

## GPU note

Phase-1 compositor is mostly CPU. Pin a small Ada/L4 class card so the account worker pool stays cheap. Future Cycles title jobs may want more VRAM; same image, larger GPU type list.
