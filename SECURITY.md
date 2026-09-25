# Security boundary

This repository is PAPER-ONLY.

## It must never contain
- exchange/API credentials, passwords, cookies, private keys, wallet seeds, account IDs, or personal data;
- live order, withdrawal, transfer, leverage, margin, futures, shorting, or deposit execution;
- GitHub Actions secrets;
- workflow permissions that can write repository contents;
- automatic execution of code supplied by external pull requests.

## GitHub Actions policy
- workflows use no repository/org/environment secrets;
- default token permissions are empty (`permissions: {}`) unless a reviewed workflow documents a narrower read-only need;
- `pull_request`, `pull_request_target`, `issue_comment`, `repository_dispatch`, and `workflow_run` triggers are forbidden for this public PAPER repository;
- third-party `uses:` actions are forbidden in the hardened baseline; jobs use the GitHub-hosted runner and fetch the exact public commit over HTTPS without credentials;
- no workflow may place orders or access an exchange account.

## Public-repository operating rule
Treat every pull request, issue, and comment as untrusted input. Never copy commands, credentials, or configuration from them into the runtime without independent review.

## If a secret is ever committed
Do not merely delete the file. Revoke/rotate the secret immediately and treat repository history and forks as exposed.
