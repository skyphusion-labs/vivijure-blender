# Changelog

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
