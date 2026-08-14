# Changelog

## Unreleased

### Fixed

- **The grade path applied Blender's default AgX view transform to display-referred
  footage, wrecking every preset (vivijure-blender#14).** `scripts/composite_job.py` set
  the render engine, resolution, fps and output format but never touched colour
  management, so `scene.view_settings.view_transform` kept its Blender 4.x default of
  `AgX` -- a filmic tone mapper built for scene-linear HDR renders. The input here is
  already display-referred (PNG frames pulled out of a finished h264 clip), so every job
  re-tonemapped an image that had already been tonemapped. It happens AFTER the
  compositor, on the way out to PNG, so it hit every preset identically and could not
  have been tuned away in the preset table.

  Measured on two live door renders, 2026-08-14:

  | run | preset | source YAVG | graded YAVG |
  |---|---|---|---|
  | `film-a0f533e0` | `high_contrast` @1.4 | 102.14 | 34.45 |
  | `film-8f704826` | `neutral` @1.0 (identity) | 91.90 | 27.35 |

  The second is the one that settles it: `neutral` at strength 1.0 is a mathematical
  identity in the preset table (gamma 1.0, lift 0, gain 1, saturation 1), so the
  ColorBalance and HueSat nodes are no-ops -- and the clip still came back 3.3x darker
  with a heavy red cast. The grade math was never the cause.

  Fixed by pinning `view_transform="Standard"`, `look="None"`, `exposure=0`, `gamma=1`
  and `display_device="sRGB"` explicitly, with NO `try/except` around them: a silently
  skipped colour-management write is exactly this defect, and it reads as a clean run.

  Guarded by `tests/test_color_management.py`, which is a SOURCE guard because CI has no
  Blender and because no existing gate can see this -- the job exits 0, writes the right
  frame count, and produces a structurally valid mp4 of the right dimensions and
  duration. Only the pixels are wrong. The guard was driven RED against the pre-fix
  source before being trusted green.

## 0.2.0 -- 2026-08-08

### Added

- **Resident serve overlay (`Dockerfile.serve`, `serve.py`, `runpod_http_serve.py`).** The
  door can now run as an always-on HTTP service on our own hardware instead of a RunPod
  serverless worker, speaking the same `/run` + `/status` contract. Ported from
  `vivijure-audio-upscale`; the job shape already transferred, since blender takes a clip
  and returns a graded clip over R2 and answers with a small JSON result rather than a
  blob. `CMD` is `python3`, not `python`: this base image has no `python` binary, which
  also defeats any `python -c` healthcheck copied from the media stack.
- **`-serve` images are built and published by CI**, as `<tag>-serve` for every release
  tag, from the same source tree as the release image they are based on. Before this,
  nothing anywhere built a serve image for this repo.
- **Secrets can arrive as files.** `serve.py` fills `NAME` from `NAME_FILE` at start, the
  standard Docker and swarm convention, so a stack never has to carry a plaintext value in
  an `environment:` block. An already-set `NAME` always wins, so a door that passes plain
  environment variables cannot be overridden by a stale secret file. The startup line
  prints the NAMES it filled and never the values.

### Fixed

- **An oversize or unparseable request body was accepted as an EMPTY job.** `_body()`
  answered `None` for three different situations (no body at all, a body past the 1 MiB
  cap, and a body that would not parse), and `/run` then did
  `payload = (body or {}).get("input", body or {})`, so all three were accepted with a
  `200` and a job id and ran with no input at all. The caller received a success shape for
  a request that was never honoured, and the job failed later naming a missing field
  rather than naming the body. Now `413` and `400` respectively, checked AFTER
  authentication so an unauthenticated caller still gets `401` and learns nothing about
  the cap. The memory-DoS half of the cap always worked, since an oversize body is never
  read into memory, and that is exactly why the semantics half went unnoticed.

### Changed

- CI builds the release image with plain `docker build` plus a separate push rather than
  `docker/build-push-action`. The serve overlay builds `FROM` the release image and must
  resolve it LOCALLY; buildx leaves it in the buildkit cache, so the overlay would
  silently re-resolve its base from the registry and build on whatever GHCR happened to
  hold. That failure has no tell: the build succeeds and the log is identical. Two
  controls now guard it, requiring the base to be among the tags the job just built and
  to be present locally.

## 0.1.1 -- 2026-08-07

### Fixed

- **Every job failed.** `composite_job.py` wrote sequence framing onto the Image
  datablock: `frame_duration` is read-only in Blender 4.2.8 LTS and `frame_start` /
  `frame_offset` are not attributes of `Image` at all, so all three raised. Five sites
  in total (three on the main clip, two more on the plate in `composite` jobs). Framing
  belongs on the node's image_user, which was already being set correctly in both paths,
  so this is a deletion.
- **The render step now verifies its own output.** `blender -b --python` exits 0 when the
  script dies on an uncaught exception, so a returncode check could not observe a crashed
  render; the failure surfaced two steps later as an ffmpeg error about a missing input
  pattern, naming the wrong component. `_run_blender` now checks frames written against
  frames requested and carries blender's own output into the error, which a zero exit
  previously discarded.

### Changed

- CI: added the `coverage`, `CodeQL` and `audit` gates and a `ci` lint/compile job,
  ported from `vivijure-audio-upscale`. The repo produced none of the status checks its
  org ruleset requires, so no pull request here could merge.
- Dropped an unused `shutil` import (`handler.py`), which the new lint gate refuses.

## 0.1.0 -- 2026-08-07

### Added

- Initial satellite: headless Blender LTS compositor on RunPod serverless.
- Job types: `grade` (presets: neutral, filmic_warm, high_contrast, cool, soft) and `composite` (plate underlay).
- R2 finish-chain + presigned URL transport; `{"selftest": true}` harness.
- `deploy.sh` + Dockerfile (Blender 4.2.8 LTS).
