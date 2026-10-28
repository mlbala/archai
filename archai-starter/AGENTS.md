# ArchAI repository instructions

## Project contract

- Build ArchAI, repository/package `archai`, primary CLI `arch`, executable alias `archai`.
- Read `BUILD_PROMPT.md` for the complete implementation contract and `ARCHITECTURE.md` for the companion design.
- `arch auto` consumes complete requirements, coordinates all applicable components, and generates the complete AI system design and documents.
- Individual commands such as `arch system`, `arch infra`, and `arch guard` design only that component and automatically create its standalone design document.
- Preserve explicit user decisions and locks. Use shared validated project state for all generated documents and configurations.
- Implement and verify real functionality; report missing dependencies and blocked requirements accurately.
- Preserve existing user changes. Never deploy generated cloud infrastructure as part of building the designer.
- Preserve the repository owner's license decision. `LICENSE-MIT.template` is an unselected template; do not activate it, invent a copyright holder, or declare the project MIT-licensed without the owner's choice.

## Git identity and attribution

- For every new commit created for this user, use only the user's configured Git name/email as author and committer.
- Before committing, inspect effective identity with `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`, including any environment overrides. If the expected user identity is missing or ambiguous, ask before committing; continue non-Git implementation work where possible.
- Never use an assistant/bot identity or infer the user's identity from a directory or account name.
- Never add `Co-authored-by:` trailers, AI `Signed-off-by:` trailers, `Generated-by:` trailers, or “Generated with Codex/Copilot/Claude” credit to new commit messages.
- Preserve the user's required sign-off and signing settings. Never impersonate a signer.
- Before an authorized push, resolve its outgoing range and inspect all new agent-created commits for author, committer, and unwanted attribution. A push does not change commit authorship.
- Report attribution mismatches before pushing. Do not rewrite existing/published history, force-push, or remove legitimate third-party attribution to satisfy this policy.
- Do not change global Git configuration, authentication, hooks, or signing settings. Repository-local identity changes must use the user's supplied values.
- Building the project does not itself authorize a push. Do not create commits merely to test attribution.

## Validation

- Follow the full build prompt's acceptance tests and check installed-package behavior as well as source-tree behavior.
- Use formatting, linting, typing, tests, and package-build checks appropriate to the implemented milestone.
- Report checks that actually ran, failures, and skipped optional checks; do not present simulation or syntax validation as a deployed system.
