# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This is a single-context repo:

- `CONTEXT.md` at the repo root for domain language, when it exists
- `docs/adr/` for architectural decisions, when ADRs exist

If these files do not exist, proceed silently. Do not create them upfront just because they are missing; producer workflows such as `grill-with-docs` can create them when terms or decisions actually get resolved.

## Reading Rules

- Read `CONTEXT.md` before exploring if it exists
- Read relevant ADRs under `docs/adr/` before changing an area they cover
- Use domain terms as defined in `CONTEXT.md`
- If output contradicts an existing ADR, surface the conflict explicitly
