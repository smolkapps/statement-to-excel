# Worklog

## 2026-10-16 — Studio CI migration

Goal: execute existing CI on the local Studio with explicit hosted rollback.

Changed only runs-on selection to the per-repository STUDIO_CI profile(s), retaining a unique admitted run label. Public fork pull requests retain their original hosted runner label. Linux retains worker resource/core protections, backend tests, synthetic accuracy, routing and real browser/workbook checks; no test weakening. All triggers, job IDs, matrix values, conditions, services, steps and publication gates are preserved.

Validation: parsed before/after workflow comparison permits only runs-on changes; runner variables and default/hosted/fork resolutions checked with a sample run ID. No builds, tests, installs, dispatches, deployments, releases, commits or API writes were performed during preparation. Actual admitted runtime validation remains after central review/application.

Hosted rollback values (JSON quotation marks are required): STUDIO_CI_UBUNTU_LATEST = "ubuntu-latest". Browser OS dependencies are installed centrally in the Linux VM; the nonadmin Studio job installs the same pinned Chromium without sudo. Hosted runs retain the original --with-deps command. No suites are removed. Pinned Playwright1.58.2 lacks an Ubuntu26 platform entry, so Studio selects its upstream Ubuntu24 ARM64 compatibility target for install/run and verifies the actual browser suites. Browser revision and tests stay pinned.
