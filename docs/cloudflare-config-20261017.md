# Existing Cloudflare site configuration

Goal: enable consented Web Analytics on this app through the existing owner-controlled smolkin.org site, with separate hostname reporting. This changes only the existing public production setting.

- Base: `231d3c7bf6679ba92c75458abd6ee0471c4d94b5`.
- Configured key: `VITE_CF_WEB_ANALYTICS_TOKEN` in `frontend/.env.production`. Google remains unconfigured.
- Existing site tag: `fbd660019e7042838465f6232ba06634`; its beacon identifier is public, not an API credential. Account/site/DNS/security settings are unchanged.
- [Cloudflare documents same-apex subdomain reuse](https://developers.cloudflare.com/web-analytics/faq/#can-i-use-the-same-js-snippet-for-a-different-domain).
- Parent read-only checks confirmed the enabled owner site and current SDK matching reviewed SHA256 `637381256384554e1cc3309a62fb238a51b83e7f10b2a56d8ba15dbc73ca762e` and the existing SRI. Consent/context/privacy guards are unchanged.
- Native Mac Studio arm64 Node24 checks: 215/215 frontend tests across13files; TypeScript, SEO checks and Vite production build pass. Dependency installs use the unchanged lockfiles.
- At this configuration checkpoint, actual provider ingestion and production delivery have not been performed. Subsequent runtime evidence is recorded in the central portfolio operations record; this commit does not claim it.
- Backend source, API routes, billing and existing Linux/backend/accuracy evidence are unchanged; the earlier Mac memory-limit failure is not rerun or claimed fixed. No payment/lifecycle matrix or native phone/simulator test was performed.
