# Trello Project Workflow Skill for Codex

A Codex skill and dependency-free Python helper for safe project-specific Trello workflows.

It supports:

- project-local semantic list and label mappings,
- priority-ordered card selection with required/excluded labels,
- rich card context including creator, comments, members, attachments, checklists, and state history,
- idempotent label changes,
- guarded, recoverable card claims with optimistic concurrency checks,
- normal create/comment/move/resume/finish workflows,
- dry-run previews for every mutating workflow command.

The helper intentionally does not delete, archive, close, bulk edit, merge, or deploy anything.

## Install and update

Install the whole skill folder under the exact name `trello-project-workflow`:

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/mattivilola/trello-project-workflow-skill-for-codex.git \
  "$HOME/.codex/skills/trello-project-workflow"
```

Update an existing installation:

```bash
git -C "$HOME/.codex/skills/trello-project-workflow" pull --ff-only
```

Start a new Codex session if an existing session does not discover the updated instructions.

## Trello credentials

The helper reads `TRELLO_KEY` and `TRELLO_TOKEN` from its environment. Never put either value in project configuration or source control.

```bash
export TRELLO_KEY="your_api_key"
export TRELLO_TOKEN="your_generated_token"
```

Trello user tokens grant access on behalf of the authorizing account. For unattended agents, use a dedicated automation account that has access only to the required boards. See Atlassian's [authorization guide](https://developer.atlassian.com/cloud/trello/guides/rest-api/authorization/).

## Project configuration

Each project uses `.codex/trello.json`:

```json
{
  "board": {
    "name": "Example Board",
    "idOrShortLink": "8M3BYzc0"
  },
  "lists": {
    "backlog": "Round Backlog",
    "analyzed": "Analyzed",
    "start": "In Progress",
    "implemented": "Dev Ready",
    "verification": "In Verification",
    "verificationReady": "Verification Ready",
    "verified": "In Staging",
    "done": "In Production/Done"
  },
  "labels": {
    "aiReady": "AI Ready",
    "aiManaged": "AI Managed",
    "aiNeedsInput": "AI Needs Input",
    "aiHold": "AI Hold"
  },
  "cardDefaults": {
    "prefix": "v3",
    "position": "top"
  }
}
```

Semantic keys let prompts and automation remain stable if a visible Trello name changes. `config-check` fails when any configured list or label cannot be resolved uniquely.

Preview configuration generation:

```bash
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" init-config \
  --board-url "https://trello.com/b/8M3BYzc0/example-board" \
  --board-name "Example Board" \
  --start-list "In Progress" \
  --implemented-list "Dev Ready" \
  --verified-list "In Staging" \
  --list backlog="Round Backlog" \
  --list analyzed="Analyzed" \
  --label aiReady="AI Ready" \
  --label aiManaged="AI Managed"
```

Add `--write` only after reviewing the preview. Existing configuration is protected unless the user explicitly passes `--force`.

## Read and selection commands

```bash
helper="$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py"

python "$helper" config-check
python "$helper" lists
python "$helper" labels
python "$helper" whoami
python "$helper" cards --list-key backlog
python "$helper" next-card --list-key backlog \
  --require-label aiReady \
  --exclude-label aiHold
python "$helper" card-context --card abc123 --actions-limit 100
```

`next-card` returns the highest eligible card according to Trello position. It prints JSON `null` with exit status 0 when nothing qualifies.

`card-context` returns the card's description, current list and labels, creator, members, attachments, ordered checklists, and chronological actions. Actions include comments, creation, list movements, and label changes.

## Labels

Label references may be semantic keys from the project configuration or literal board label names. Resolution is exact, case-insensitive, and rejects missing or ambiguous labels.

```bash
python "$helper" add-label --card abc123 --label aiNeedsInput --dry-run
python "$helper" remove-label --card abc123 --label aiNeedsInput --dry-run
```

Both operations are idempotent.

## Guarded claims

Use `next-card`, retain its `dateLastActivity`, then claim that exact state:

```bash
python "$helper" claim \
  --card abc123 \
  --from analyzed \
  --to start \
  --expected-last-activity "2026-07-30T10:00:00.000Z" \
  --require-label aiManaged \
  --exclude-label aiHold \
  --comment "[Codex Dev] Claimed for implementation." \
  --dry-run
```

A claim rejects closed cards, wrong source lists, stale activity timestamps, missing required labels, and present excluded labels. On success it moves the card first, applies requested label changes, and adds the comment. A retry after an interruption detects that the card is already in the target list, repairs requested label changes, and avoids duplicating the comment.

Trello does not expose a multi-request transaction, so use one process per stage and an external process lock in unattended automation.

## AI workflow convention

- A human adds `AI Ready` to authorize Analyst review.
- Analyst asks the creator for missing information with `AI Needs Input` and waits for a later reply.
- Analyst removes `AI Ready`/`AI Needs Input` and moves complete analysis to `Analyzed`.
- Analyst does not add `AI Managed`; a human adds it after reviewing the analysis.
- Dev and QA require `AI Managed` and exclude `AI Hold` for every claim.
- `AI Hold` pauses automation regardless of stage.

## Normal task commands

```bash
python "$helper" create --title "Task title" --desc "Short context" --list-key start
python "$helper" comment --card abc123 --text "Focused tests passed."
python "$helper" resume --card abc123
python "$helper" finish --card abc123 --overview "Implemented and locally verified."
```

## Tests

The helper uses only the Python standard library. Run the offline regression suite with:

```bash
python -m unittest discover \
  -s "$HOME/.codex/skills/trello-project-workflow/tests" \
  -v
```

Live verification should use read-only commands and `--dry-run` before any mutation.
