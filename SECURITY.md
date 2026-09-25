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
- token permissions remain empty with `permissions: {}`;
- `pull_request`, `pull_request_target`, `issue_comment`, `repository_dispatch`, and `workflow_run` triggers are forbidden;
- the only external action allowed is GitHub-owned `actions/cache`, pinned to immutable commit `0057852bfaa89a56745cba8c7296529d2fc39830`;
- the exact public commit is fetched over HTTPS without repository credentials;
- no workflow may place orders or access an exchange account.

## Public-repository operating rule
Treat every pull request, issue, and comment as untrusted input. Never copy commands, credentials, or configuration from them into the runtime without independent review.

## If a secret is ever committed
Do not merely delete the file. Revoke/rotate the secret immediately and treat repository history and forks as exposed.
