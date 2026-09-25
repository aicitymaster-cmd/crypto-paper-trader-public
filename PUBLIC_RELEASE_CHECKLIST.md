# Public release checklist

- [x] Local unit tests pass: 242 tests.
- [x] Local `python security_guard.py .` prints `SECURITY_GUARD_OK`.
- [x] No API key, password, token, cookie, wallet seed, private key, account identifier, email, phone, address, or personal name is used by the PAPER runtime.
- [x] No live order, transfer, withdrawal, deposit, leverage, margin, futures, or shorting execution exists.
- [x] No GitHub Actions secret is referenced.
- [x] Workflow token permissions are empty: `permissions: {}`.
- [x] No external-PR-triggered workflow exists.
- [x] The only external Action is GitHub-owned `actions/cache`, pinned to immutable commit `0057852bfaa89a56745cba8c7296529d2fc39830`.
- [ ] Default branch protection/ruleset must still be verified in repository settings.
- [x] Only this PAPER repository is public; AI CITY remains separate.
