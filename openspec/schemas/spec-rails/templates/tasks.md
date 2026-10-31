# Tasks

## 1. Dependency DAG
<!-- Mermaid DAG of slices and streams. -->

## 2. Streams & Worktrees
| Stream | Worktree Path | Branch | Prerequisite |
| :--- | :--- | :--- | :--- |

## 3. Slice 1: <!-- name -->

- [ ] 3.1 BDD scenarios for the slice (verify: `.feature` committed)
- [ ] 3.2 Gate 5.1 human sign-off on BDD scenarios
- [ ] 3.3 Red unit tests fail for the expected reason (verify: output shown; on ticking append `Evidence: <command and result>`)
- [ ] 3.4 Green implementation, tests and code committed together (verify: suite passes; on ticking append `Evidence: <command and result>`)
- [ ] 3.5 Coverage >= 95% and mutation 100% kill (verify: reports; on ticking append `Evidence: <command and result>`)

## 4. Integration & Rebase Plan
- [ ] 4.1 Merge streams, rebase on main, re-verify rails, `openspec archive`

## Review Gate
- [ ] **Gate 4 Approval**: Tasks breakdown approved by human before writing test code.
