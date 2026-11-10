# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately to hello@query.farm. Do not
open a public issue until Query Farm has acknowledged the report and coordinated
disclosure.

Include the affected version, deployment mode, reproduction steps, and potential
impact. We will acknowledge reports within three business days and provide status
updates while the issue is investigated.

## Supported versions

Security fixes are applied to the latest released minor version. Older releases
may require upgrading to receive a fix.

## Deployment boundary

The stdio worker communicates only with its parent process. HTTP deployments must
use a stable `VGI_SIGNING_KEY` and either VGI authentication or a trusted
authenticating proxy. The `vgi-soccer-http` entry point enforces this policy unless
anonymous access is explicitly enabled with `VGI_ALLOW_ANONYMOUS=1`.

## Upstream boundary

The worker only issues HTTP GET requests to its configured upstream roots
(ESPN, openfootball on GitHub, OpenLigaDB). League slugs, shortcuts and numeric
identifiers are validated before they are placed in a request path. The
`SOCCER_*_URL` and `SOCCER_MIN_REQUEST_INTERVAL` overrides exist for hermetic
tests and must never be derived from untrusted input.
