# Security Policy

## Supported Versions

Sprint Pulse is released from `main`; only the latest commit on `main` is
supported with security fixes.

## Reporting a Vulnerability

Please **do not open a public issue** for security problems. Instead, use
GitHub's private vulnerability reporting:

**[Report a vulnerability](https://github.com/omaciel/sprint-pulse/security/advisories/new)**

Include what you can: affected version/commit, reproduction steps, and impact.
You'll get an acknowledgment within a few days, and a fix or mitigation plan
before any public disclosure is coordinated.

## Scope notes

- Sprint Pulse is designed for a **single operator** on a trusted host or
  private network; the web UI has no authentication by design. Reports that
  assume an untrusted multi-user deployment of the dashboard itself are out
  of scope — but anything that lets a remote party reach the operator's Jira
  credentials is very much in scope (see the Jira host allowlist in
  `sprint_pulse/config.py:validate_site`).
- The Jira API token is never stored in the database or repository — keyring
  on desktop, `JIRA_API_TOKEN` env in containers.
