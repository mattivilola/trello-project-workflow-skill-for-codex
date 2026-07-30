---
name: trello-project-workflow
description: Use when a project has `.codex/trello.json`, or when the user asks Codex to configure Trello, inspect prioritized cards and context, manage labels, safely claim work, create/comment/move cards, complete work, verify work, or pull incoming bugs. Supports project-specific boards, semantic list and label mappings, creator/comment/checklist context, and guarded AI-agent handoffs.
metadata:
  short-description: Manage project Trello cards
---

# Trello Project Workflow

Use the bundled helper script instead of browser automation when Trello API credentials are available.

## Setup Workflow

If `.codex/trello.json` is missing or the user asks to configure Trello for a project:

1. Ask for the Trello board URL or short link. If the user has a board visible, ask for a screenshot/appshot and extract the board URL, board name, visible lists, and relevant labels.
2. Ask which visible list corresponds to each semantic phase. Core keys are `start`, `implemented`, and `verified`; optional keys include `backlog`, `analyzed`, `verification`, `verificationReady`, `incomingBugs`, and `done`.
3. Ask which labels act as workflow gates. Use semantic label keys such as `aiReady`, `aiManaged`, `aiNeedsInput`, and `aiHold` when appropriate.
4. Use `init-config` first without `--write` to preview the JSON.
5. Write the config only after the user confirms the mappings, using `--write`. Do not overwrite an existing config unless the user explicitly approves it and `--force` is passed.
6. Never place `TRELLO_KEY`, `TRELLO_TOKEN`, or other Trello secrets in `.codex/trello.json`.

Example optional label mapping:

```json
{
  "labels": {
    "aiReady": "AI Ready",
    "aiManaged": "AI Managed",
    "aiNeedsInput": "AI Needs Input",
    "aiHold": "AI Hold"
  }
}
```

## Triggered Workflow

1. Find project config by walking upward from the current working directory until `.codex/trello.json` is found.
2. Use `TRELLO_KEY` and `TRELLO_TOKEN` from the environment. Never ask for or store Trello credentials in project files.
3. Run `config-check` before relying on configured list or label keys.
4. Use `next-card` for priority selection. Trello's top card is returned first; required and excluded labels are resolved exactly and case-insensitively.
5. Use `card-context` before analysis or implementation when creator, comments, members, attachments, checklists, or list/label history matters.
6. Use `claim` before starting automated work. Pass the source and target semantic list keys, required/excluded labels, and the `dateLastActivity` returned by `next-card` as `--expected-last-activity`.
7. A guarded claim verifies current state, moves the card first, then applies idempotent label changes and adds the claim comment. A retry in the target list repairs interrupted label changes without duplicating the comment.
8. Create or move cards according to the project's configured keys. Place moved cards at the top unless the user says otherwise.
9. If credentials/config are missing or a claim is rejected as stale, stop that workflow action and report it; do not bypass the guard with an unverified plain move.
10. Keep Trello comments concise and structured. Never include secrets, production/customer-specific data, private debugging details, or long logs.

## AI-Managed Card Gate

When a project uses the `AI Ready`, `AI Managed`, `AI Needs Input`, and `AI Hold` convention:

- `AI Ready` is human authorization for Analyst review only.
- Analyst may analyze only a top-priority card with `AI Ready` and without `AI Hold`.
- If clarification is needed, Analyst adds `AI Needs Input`, asks the creator with an explicit `@username` mention, and waits for a later human comment before continuing. Do not repeat unchanged questions.
- When analysis is complete, Analyst removes `AI Ready` and `AI Needs Input`, moves the card to `Analyzed`, and does **not** add `AI Managed`.
- A human reviews the analysis and adds `AI Managed`; this is the authorization gate for autonomous Dev and QA work.
- Dev and QA require `AI Managed` and exclude `AI Hold` at every claim. Preserve `AI Managed` through the pipeline.
- `AI Hold` always wins: do not claim or continue held work unless the owner explicitly removes the label.

For Aalto, the intended managed flow is:

`Round Backlog` → `Analyzed` → `In Progress` → `Dev Ready` → `In Verification` → `Verification Ready` → `In Staging` → `In Production/Done`.

Dev branches from the latest `development` branch in an isolated worktree. QA uses a separate worktree, verifies the exact Dev branch, adds missing tests when appropriate, and may merge a passing branch into the latest `development` only when the project automation policy explicitly authorizes that merge. Never deploy automatically.

## Standard Project Workflow

- Create normal task cards in `start`/`In Progress` when implementation begins.
- Move cards to `implemented`/`Dev Ready` after implementation and local verification, with a compact overview comment.
- Move cards to `verified` when the user confirms verification or staging handoff.
- If the same task continues after reaching `implemented`, use `resume` to return that card to `start` and add a short comment.
- If a new request has materially different scope, create a separate card rather than reusing an unrelated card.
- Prefer `finish --overview "..."` for normal task completion.

## Helper Script

Run from any configured project directory:

```bash
helper="$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py"

python "$helper" config-check
python "$helper" lists
python "$helper" labels
python "$helper" whoami
python "$helper" cards --list-key backlog
python "$helper" next-card --list-key backlog --require-label aiReady --exclude-label aiHold
python "$helper" card-context --card abc123 --actions-limit 100
python "$helper" add-label --card abc123 --label aiNeedsInput --dry-run
python "$helper" remove-label --card abc123 --label aiNeedsInput --dry-run
python "$helper" claim --card abc123 --from analyzed --to start \
  --expected-last-activity "2026-07-30T10:00:00.000Z" \
  --require-label aiManaged --exclude-label aiHold \
  --comment "[Codex Dev] Claimed for implementation." --dry-run
python "$helper" create --title "Task title" --desc "Short context" --list-key start
python "$helper" comment --card abc123 --text "Implemented and locally verified."
python "$helper" resume --card abc123
python "$helper" finish --card abc123 --overview "Updated workflow behavior and focused tests passed."
```

`next-card` prints JSON `null` and exits successfully when nothing is eligible. Repeated label flags are cumulative: every `--require-label` must be present, while any `--exclude-label` prevents selection or a claim.

Use `--dry-run` on `init-config`, `create`, `move`, `comment`, `add-label`, `remove-label`, `claim`, `resume`, and `finish` when checking intent without mutation.

## Safety

- Do not delete, archive, close, bulk edit, merge, deploy, or otherwise perform destructive/external operations unless the user explicitly authorizes that exact phase.
- Label changes are restricted to existing, uniquely named board labels; this helper never creates labels implicitly.
- `claim` is guarded and recoverable but Trello does not provide a multi-request transaction. Use one active agent per stage plus an external lock.
- Treat `dateLastActivity` as an optimistic concurrency guard. If it changes, reread the card instead of forcing the move.
- A Trello user token grants access to that user's account. Prefer a dedicated automation user invited only to the required board.
