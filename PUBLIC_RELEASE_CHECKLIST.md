# Public release checklist

Release is blocked unless every item is true.

- [ ] `python -m unittest discover -v` passes.
- [ ] `python security_guard.py .` prints `SECURITY_GUARD_OK`.
- [ ] No API key, password, token, cookie, wallet seed, private key, account identifier, email, phone, address, or personal name is present.
- [ ] No live order, transfer, withdrawal, deposit, leverage, margin, futures, or shorting execution exists.
- [ ] No GitHub Actions secret is referenced.
- [ ] Workflow permissions are empty or explicitly read-only.
- [ ] No external-PR-triggered workflow exists.
- [ ] No third-party GitHub Action is used in the hardened baseline.
- [ ] Default branch is protected from force-push and deletion before public operation begins.
- [ ] Only the PAPER repository is public; AI CITY and private work remain separate.
