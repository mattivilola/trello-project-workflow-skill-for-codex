---
name: trello-project-workflow
description: Use when a project has `.codex/trello.json`, or when the user asks Codex to set up Trello workflow config, create, read, list, update, comment on, move, complete, verify, or pull work from Trello cards. Supports project-specific Trello boards and list phases, including creating a task card at start, moving it to implemented/dev-ready after local completion, moving it to verification/staging after user verification, and pulling cards from an incoming bug-report list.
metadata:
  short-description: Manage project Trello cards
---

# Trello Project Workflow

Use the bundled helper script instead of browser automation when Trello API credentials are available.

## Setup Workflow

If `.codex/trello.json` is missing or the user asks to configure Trello for a project:

1. Ask for the Trello board URL or board short link. If the user has a Trello board visible, ask for a screenshot/appshot and extract the board URL, board name, and visible list names from it.
2. Ask which visible list corresponds to each semantic phase: `start`, `implemented`, `verified`, and optionally `incomingBugs` and `done`.
3. Use `init-config` first without `--write` to preview the JSON.
4. Write the config only after the user confirms the mapping, using `--write`. Do not overwrite an existing config unless the user explicitly asks for overwrite and `--force` is passed.
5. Never place `TRELLO_KEY`, `TRELLO_TOKEN`, or Trello API secrets in `.codex/trello.json`.

## Triggered Workflow

1. Find project config by walking upward from the current working directory until `.codex/trello.json` is found.
2. Use `TRELLO_KEY` and `TRELLO_TOKEN` from the environment. Never ask for or store Trello credentials in project files.
3. Resolve configured list names to list IDs with the helper script.
4. Create or move cards according to the project's configured list keys. When moving a card to another list, place it at the top of the destination list.
5. If credentials or config are missing, state the missing item and continue the user's coding task without Trello mutation.
6. When creating a card, let the helper apply `cardDefaults.prefix`. Do not manually include `Codex:` or any other prefix in the title unless that exact prefix is configured.
7. If a chat continues after a card was moved to `implemented`/Dev Ready and the new work is clearly a continuation of the same task, move the same card back to the top of `start`/In Progress and add a short generic resume comment.
8. If the new request has materially different scope, a different feature, or enough new work to deserve separate tracking, leave the previous card where it is and create a new card in `start`.
9. When finishing a task, add a compact final overview comment to the card before or while moving it to `implemented`. Include what changed and the main verification result in one short sentence.

## Status Conventions

The helper uses semantic list keys from `.codex/trello.json`:

- `start`: where a new Codex task card is created when work starts.
- `implemented`: where the card moves after implementation and local verification pass.
- `verified`: where the card moves after the user says the task is verified or ready for staging verification.
- `incomingBugs`: where capture.dev or incoming bug cards are pulled from.
- `done`: optional destination for completed work.

For Aalto, follow this flow unless the user says otherwise:

- Create simple task cards in `In Progress` when starting a task.
- Move cards to the top of `Dev Ready` after implementation and local verification, with a compact overview comment.
- Move cards to the top of `In Staging/Verification` when the user confirms verification or staging handoff.
- When continuing work on an existing task that is already in `Dev Ready`, move that same card back to the top of `In Progress`.
- Add concise Trello comments for meaningful status changes or implementation notes, for example `Work resumed: continuing implementation on this task.` or `Implemented: updated workflow behavior and local validation passed.`
- On final implementation completion, prefer `finish --overview "..."` over a plain move. Keep the overview generic but informative, such as `Updated workflow rules and validated helper dry-runs.`
- Keep comments generic and short. Do not include secrets, production/customer-specific data, long logs, or private debugging details.
- Read candidate cards from `Capture.dev Bug Reports` when the user asks to pull bug work.

## Helper Script

Run from any project directory:

```bash
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" init-config --board-url "https://trello.com/b/8M3BYzc0/board-name" --board-name "Board Name" --start-list "In Progress" --implemented-list "Dev Ready" --verified-list "In Staging/Verification"
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" config-check
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" lists
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" cards --list-key incomingBugs
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" card --card "abc123"
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" create --title "task title" --desc "Short task context" --list-key start
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" resume --card "https://trello.com/c/abc123/card-name"
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" finish --card "https://trello.com/c/abc123/card-name" --overview "Updated workflow rules and validated helper dry-runs."
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" move --card "https://trello.com/c/abc123/card-name" --to implemented --comment "Implemented: local validation passed."
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" comment --card "abc123" --text "Implemented and locally verified."
```

Use `--dry-run` on `create`, `move`, `resume`, `finish`, and `comment` when checking intent without changing Trello.

## Safety

Do not delete, archive, close, bulk edit, or otherwise destructively mutate Trello cards. This skill intentionally supports only read, create, move, and comment operations.
