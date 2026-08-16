# Changelog

## Unreleased

### Fixed

- **Finish guards summed above the 5400s phase ceiling, so one attempt could
  not complete and the film died as "stalled, no progress" (vivijure-blender#17).**
  `_process` runs download, extract, ffprobe, blender, encode, and upload
  sequentially; the per-leg caps SUM. Old defaults (DOWNLOAD/UPLOAD 900,
  FFMPEG 1200, BLENDER 1800) added to 6180s grade / 8280s composite against
  `PHASE_HARD_DEADLINE_SECONDS = 5400` in vivijure-core. New defaults 300 /
  300 / 480 / 1800 (blender unchanged; it is the work) add to 3540s grade /
  4320s composite, 1080s under the ceiling on the longest path. The helper
  `declared_budget_seconds` reads the values the process is running with, and
  `_process` refuses an env override that would recreate the stall. The core
  ceiling is not raised. Guarded by `tests/test_budget.py`.

- **A `neutral` grade at strength 1.0 -- a mathematical identity -- crushed every clip to
  roughly a third of its luma. TWO independent defects, and neither is sufficient alone
  (vivijure-blender#14).**

  **1. Blender's lift is identity at 1.0, not 0.0.** The `PRESETS` table is authored in the
  ASC-CDL / offset convention, where lift `0.0` means no change; that is what `neutral`
  declares and what `_mix_preset` lerps toward at strength 0. Blender's
  `CompositorNodeColorBalance` in `LIFT_GAMMA_GAIN` mode uses the opposite convention --
  identity lift is `(1,1,1)`, which it ships as the node default. Passing the offset straight
  through applied a full `-1.0` lift on every job. This is the dominant term.

  **2. The default view transform is AgX.** The script set engine, resolution, fps and output
  format but never touched colour management, so `scene.view_settings.view_transform` kept its
  Blender 4.x default of `AgX` -- a filmic tone mapper for scene-linear HDR renders, applied
  after the compositor to display-referred input. Worth ~5 YAVG and ~45 YMAX (highlight
  compression).

  **Measured by driving the real `scripts/composite_job.py` against the pinned Blender 4.2.8
  LTS**, one real source frame, identity grade (`neutral` @ 1.0), YAVG of the written PNG:

  | build | YAVG | YMAX |
  |---|---|---|
  | source frame | 91.77 | 227 |
  | `origin/main` (production) | 27.94 | 180 |
  | view-transform fix ONLY | 28.93 | 220 |
  | **view transform + lift** | **92.12** | **228** |

  The third row is the reason both are listed: fixing only the view transform reads as fixed
  and is not. `view_transform` was also confirmed as `'AgX'` by querying factory settings on
  4.2.8 directly, rather than inferred from release notes.

  Colour management is pinned with **no** `try/except`, unlike the node-property writes: a
  silently skipped assignment here is the defect itself and would read as a clean run.

  Guarded by `tests/test_color_management.py`, a SOURCE guard because CI has no Blender and no
  runtime gate can see this -- the job exits 0, writes the right frame count, and produces a
  structurally valid mp4 of the correct dimensions and duration. Each defect was driven red
  SEPARATELY with the other fixed, proving the two assertion families are independent rather
  than one check wearing two names: both broken 5 failed / 3 passed; lift-only broken 1 failed
  / 7 passed; view-transform-only broken 4 failed / 4 passed; both fixed 22 passed.

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
