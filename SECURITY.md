# Security Policy

## Scope

Dory is a local-first memory library for AI agents. Security issues are most
likely to involve one of these areas:

- data integrity in the SQLite backing store
- prompt-injection or unsafe reinjection of stored memory
- exposure of sensitive memory content through tooling or visualization
- unsafe defaults in examples, CLI helpers, or benchmark scripts

## Reporting

If you find a security issue, do not open a public issue with exploit details.
Send a private report to the maintainer through the repository contact channel
or the email listed on the package/repository profile.

Include:

- affected version or commit
- impact
- reproduction steps
- whether user data exposure or corruption is involved

## Supported Fixes

Security fixes should prefer:

1. preserving data integrity over convenience
2. narrowing trust boundaries rather than adding broad filtering
3. explicit, documented tradeoffs
4. reversible changes with a documented rollback path

## Hardening Notes

For the hardening changes applied on 2026-03-29, see:

- `docs/HARDENING_2026-03-29.md`
