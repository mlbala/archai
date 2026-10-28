# Start building ArchAI

## 1. Create and clone your repository

Create an empty Git repository named `archai`, then clone it locally. You can leave the hosting service's README, gitignore, and license initialization options unchecked when using this starter; the README and gitignore are already included and the MIT license remains a template pending your choice.

The repository description can be:

> AI system-design CLI for complete enterprise architectures or individual components, with diagrams, documentation, and infrastructure configurations.

## 2. Copy the starter files into the repository root

Extract the ZIP, open its `archai-starter` folder, and copy its contents into your cloned repository. Include the hidden `.gitignore` file. `AGENTS.md` and `BUILD_PROMPT.md` should sit at the root, beside the repository's `.git` directory, rather than inside a `code` or `src` subfolder.

If the repository already has a README, AGENTS.md, gitignore, or license, merge or review those files rather than blindly replacing them. The build prompt is the latest consolidated specification; older GPU-oriented drafts are not needed.

## 3. Set your own Git identity

Run these commands from inside the cloned repository after replacing the placeholders:

```sh
git config --local user.name "YOUR NAME"
git config --local user.email "YOUR EMAIL"
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

Check that the effective author and committer are yours. `AGENTS.md` requires no Codex, Copilot, Claude, or other assistant co-author/generated-by attribution in new commit messages. A push preserves commit metadata; it does not replace the author. These are repository instructions, not a guarantee about unrelated tools or hosting-service merge behavior.

## 4. Decide whether to use MIT

If MIT is your choice, fill in the copyright holder in `LICENSE-MIT.template`, rename it to `LICENSE`, and update README's license section. Do not publish an unfinished copyright placeholder as the project's selected license. If you have not decided, leave the file as a template and keep the README's pending-choice wording.

The year is set to 2026. The holder should be the actual person or organization entitled to license the work; it is not automatically the machine username or an AI tool's name.

## 5. Open the repository in Codex

Start a chat attached to the cloned repository and send this:

```text
Read AGENTS.md and BUILD_PROMPT.md completely, then read ARCHITECTURE.md.

Implement ArchAI in this repository according to the build specification.
arch auto must create the complete AI system design and documents.
Each component command must design only that component and automatically
create its standalone design document.

Work through the implementation milestones, run the required checks, and
report actual results. Do not stop after a plan or scaffold. Preserve the
Git identity and no-AI-coauthor policy in AGENTS.md. Preserve the current
license decision; do not activate the MIT template without my choice.
```

Provide the architect-model credentials through the eventual environment configuration, not in committed files. If an API key or required external dependency is missing, the agent should explain the specific blocker while continuing useful local work.

## 6. Review the result before publishing

The build should include working CLI commands, tests, valid generated examples, and updated installation documentation. Review the checks and the recorded limitations. Commit or push when you are ready; creating the starter does not create a Git commit or remote repository.
