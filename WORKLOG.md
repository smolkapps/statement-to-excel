# Worklog

## 2026-10-16 — Studio CI migration

Goal: move the current open PR workflow source to Studio without altering its application changes or checks.

Changed workflow runner profiles to the existing per-repository local defaults with JSON hosted rollback. Keep this PR's provider-SDK downloads, STX_PROVIDER_SDK_DIR, synthetic PDF fixtures, accuracy, routing and browser assertions unchanged. Studio-only browser provisioning uses the exact previously reviewed ubuntu24.04-arm64 override plus browser-only Chromium install against centrally installed dependencies; hosted keeps --with-deps. No billing, analytics, fixtures, app code or guidance is changed. Branch/PR-only policy remains respected; no main push or merge.

Verification during preparation: parsed before/after comparison permits only the documented runner/Xcode/signing-opt-in/Studio-browser setup differences; all other job fields, triggers, steps and commands remain identical. Profile JSON resolution and added shell syntax verified. Closest branch AGENTS.md/.github/AGENTS.md/.github/workflows/AGENTS.md were read where present. No app tests, compilation, dependency install, workflow dispatch, publication or GitHub mutation executed. Parent owns source review/application and actual CI verification.

Hosted rollback: STUDIO_CI_UBUNTU_LATEST = "ubuntu-latest".
