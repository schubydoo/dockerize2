# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities **privately** via GitHub Security
Advisories: <https://github.com/schubydoo/dockerize2/security/advisories/new>.

Do **not** open a public issue for security bugs.

You should receive an acknowledgement within 72 hours. We aim to ship a
fix and coordinated disclosure within 30 days for confirmed issues.

## Supported Versions

| Version | Supported |
|---------|-----------|
| `0.3.x` | ✅ |
| `< 0.3` | ❌ (pre-fork upstream) |

## Threat model & known risks

`dockerize` analyses ELF binaries and **invokes the binary's own dynamic
loader** (`<interp> --list <binary>`) to enumerate shared-library
dependencies. This is the same approach `ldd(1)` takes and carries the
same caveat:

> **Do not run `dockerize` against untrusted binaries** outside of a
> sandbox. A crafted ELF can execute code via its dynamic loader.

The tool mitigates by sanitising the environment (`LD_*` variables
stripped) and enforcing a 15-second timeout on the loader call, but
this is defence-in-depth — not a guarantee.

## Hardening checklist (recommended for users)

- Run `dockerize` inside a container or rootless namespace when
  processing third-party binaries.
- Use `--no-host-lookup` if you don't want `/etc/passwd` / `/etc/group`
  entries from the build host to leak into the image.
- Use `--output-oci` instead of mounting the Docker socket when running
  `dockerize` itself from a container.
