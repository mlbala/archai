# ArchAI repository instructions

## Product contract

- Build and maintain ArchAI as package `archai`, primary CLI `arch`, alias `archai`.
- `arch auto` creates the complete applicable design; component commands write only their scope.
- Preserve user-set decisions, locks, immutable revisions, and the repository owner's license.
- Never deploy generated infrastructure or describe validation as deployment.

## Git identity and attribution

- Use only the user's configured Git author and committer identity for new commits.
- Before committing, run `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`.
- Never add AI attribution, `Co-authored-by`, or generated-by trailers.
- Do not rewrite existing commits, change global Git configuration, or push without explicit request.

User setup (replace placeholders yourself):

```sh
git config --local user.name "YOUR NAME"
git config --local user.email "YOUR EMAIL"
```

## Validation

Run `ruff format --check .`, `ruff check .`, `mypy src`, `pytest -q`, `python -m build`,
and an installed-wheel smoke test. Report optional renderer/Terraform checks accurately.

