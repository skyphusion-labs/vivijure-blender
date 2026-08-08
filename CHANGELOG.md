# Changelog

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
