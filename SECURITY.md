# Security

Report vulnerabilities privately to the Skyphusion Labs security contact (see the main Vivijure SECURITY docs). Do not open public issues for unfixed security bugs.

## Boundary

- **No user Python.** Jobs only pass preset names and keys; the bpy script is image-baked.
- **No free-form .blend upload** in v1.
- **R2 credentials** live only in the RunPod endpoint env (or presigned URLs). Never log secret values.
- Acceptable use: same Vivijure AUP as the rest of the constellation (no CSAM, no non-consensual intimate deepfakes).
