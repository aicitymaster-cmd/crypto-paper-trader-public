# Public release checklist

- [x] Earlier public-candidate package passed 242 local tests.
- [x] Fast sampler and fast PAPER engine passed 9 additional local tests.
- [ ] Final GitHub-hosted combined tests still need to pass.
- [x] No API key, password, wallet seed, private key, account access, or personal data is used by the PAPER runtime.
- [x] No live order, transfer, withdrawal, deposit, leverage, margin, futures, or shorting execution exists.
- [x] No GitHub Actions secret is referenced.
- [x] Workflow token permissions are empty: `permissions: {}`.
- [x] No external-PR-triggered workflow exists.
- [x] GitHub-owned `actions/cache` is pinned to immutable commit `0057852bfaa89a56745cba8c7296529d2fc39830`.
- [ ] Default branch protection/ruleset must still be configured and verified.
- [x] Scheduled operation remains disabled until protection is verified.
- [x] Only this PAPER repository is public; AI CITY remains separate.
