# Spec-Rails (Spec-Driven, Testing-Railed Development) Rules

When working in a repository containing `openspec/spec-rails/WORKFLOW.md`:

0. **Pre-Execution Invariant (Zero Direct Edits to main)**:
   - Before invoking `edit_file`, `write_file`, or running mutating commands, ALWAYS verify the active branch: `git branch --show-current`.
   - If on `main` or `master`, HALT immediately. Checkout a dedicated lane branch first. Direct edits on `main` are strictly forbidden.
1. **The Ponytail Mindset & Strict YAGNI**:
   - Strictly apply YAGNI (You Aren't Gonna Need It). Build strictly what the active capability and slice require.
   - Default answer is "No": push back on vague, unneeded, or speculative requirements before writing a line of code.
   - Boring > Clever: standard library over new dependencies, simple loops over metaprogramming acrobatics.
   - Code is a liability: smallest diff that passes all gates wins.
   - Zero unsolicited architecture: never introduce speculative abstractions, unused helper functions, premature plugin hooks, or hypothetical configuration flags.
   - **Contract Scaffolding Rail**: Before generating slice implementation, commit domain types, interface contracts, schemas, and empty function/method signatures. Agents generate logic strictly within scaffolded boundaries without inventing abstractions.
   - **Understand or Delete (Comprehension Invariant)**: Zero black-box code. If the human reviewer cannot explain every line of the diff, delete and revert it immediately. Working code without human comprehension is technical debt.
   - Out-of-Scope (YAGNI) boundaries in `proposal.md` are binding prohibitions; reject any requirement bleed.
   - Minimal blast radius: touch only files strictly necessary for the active task.
   - Ruthless deletion: delete dead code immediately upon mutation survival. Any code not provably required is dead code.
2. **Pick a Lane First**: Feature (`feat/<id>-<slug>` with dots normalized to hyphens, e.g. `W1.2` → `w1-2-<slug>`, Gates 0–6), Bugfix (`fix/<slug>`, Gates B1–B3), or Chore (`chore/<slug>`, zero behavior change, no gates). Never commit on `main`/`master`.
3. **Strict Human Gates**: Stop and obtain explicit human approval at every gate. A gate passes only when its Review Gate checkbox is ticked by a human and committed; NEVER self-tick Gate 0–4 or Gate 5.x sign-off boxes.
   - **Gated Planning & OpenSpec Commands**: Create changes with `openspec new change <id>-<slug>` and draft one artifact at a time via `openspec instructions <artifact> --change <id>-<slug>`, pausing for human Review Gate sign-off before generating the next file (note: `/opsx-propose` drafts all planning artifacts in one pass, which blocks commits under `spec-rails-check` until Gates 0–3 are reviewed and ticked). Run `/opsx-apply` and `/opsx-archive` (`openspec archive <id>-<slug> --yes`) only after Gate 4 is ticked by a human.
   - **Features**: Gate 0 (`research.md`) → Gate 1 (`proposal.md`) → Gate 2 (`specs/<cap>/spec.md` OpenSpec delta specs, see WORKFLOW §7) → Gate 3 (`design.md`) → Gate 4 (`tasks.md`) → Gate 5.x (BDD per slice) → Gate 6 (Sync, Archive, Merge; `openspec archive`).
   - **Bugs**: Spawn `.worktrees/fix-<slug>` off `main` first → Gate B1 (`docs/bug-reports/<date>-<slug>.md` inside worktree) → Gate B2 (Red regression test shown, uncommitted) → Gate B3 (Green fix + docs/spec sync + merge).
4. **Testing Rails**:
   - Red before Green. Red tests are never committed alone; commit them together with Green.
   - $\ge 95\%$ line and branch coverage; $> 90\%$ mutation kill score on core business logic (kill or delete dead code; justify every remaining survivor in the PR).
   - Never delete assertions, skip failing tests, or write vacuous tests.
5. **Commit & Merge Hygiene**:
   - Pre-commit hooks installed; run linters, formatters, and the full suite before every commit. Never `--no-verify`.
   - Inspect `git status` and `git diff` before every commit.
   - Before any merge: rebase onto target, re-verify rails, merge `--ff-only`.
   - After any worktree merge: immediately remove worktree (`git worktree remove`), delete branch (`git branch -d`), and prune metadata (`git worktree prune`).
   - `docs/ROADMAP.md` changes only on `main` via `chore/roadmap-<id>`.
6. **LGTM Directive Preemption**: Review directives (`#ref file:line`) in `.lgtm/reviews/` or chat preempt all forward work. Halt `tasks.md`, resolve, verify, then resume.
