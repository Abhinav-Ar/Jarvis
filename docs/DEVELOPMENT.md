# Development workflow

## Daily loop

1. Make changes under `src/orion`, `packaging`, `scripts`, or `tests`.
2. Add a regression test for every repaired failure mode.
3. Run `./scripts/check.sh` before deployment.
4. Run `./install-background.sh` only after the checks pass.
5. Verify the service with `./orionctl status` and inspect recent structured logs
   with `./orionctl logs` when behavior differs from tests.

## Change policy

- Preserve user project files and unrelated working-tree changes.
- Keep secrets in `.env`; commit only `.env.example` placeholders.
- Prefer deterministic local recovery before paid model calls.
- Require observable evidence before reporting an external action complete.
- Keep macOS permission and launchd identifiers migration-compatible unless a
  dedicated migration is designed and tested.

## Definition of done

A change is complete when syntax checks pass, the full suite passes, deployment
paths match the source layout, the background runtime loads, and the user-facing
behavior has an evidence-backed verification path.
