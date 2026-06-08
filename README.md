# Trello Project Workflow Skill for Codex

A Codex skill for tracking project work in Trello with project-local board and list configuration.

The skill helps Codex:

- create a Trello card when work starts,
- move the card through project phases such as `In Progress`, `Dev Ready`, and `In Staging/Verification`,
- move a card back to `In Progress` when the same chat/task continues,
- add compact implementation/status comments,
- initialize `.codex/trello.json` for each project.

The helper uses Trello's REST API with an API key and user token. Trello's official getting-started guide explains that you need an API key and can use the token link beside it to authorize a token: <https://support.atlassian.com/trello/docs/getting-started-with-trello-rest-api/>. Atlassian's REST authorization guide documents token-based REST authorization: <https://developer.atlassian.com/cloud/trello/guides/rest-api/authorization/>.

## Install

Clone this repository into Codex's skills directory using the skill folder name `trello-project-workflow`:

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/mattivilola/trello-project-workflow-skill-for-codex.git "$HOME/.codex/skills/trello-project-workflow"
```

Start a new Codex session after installing so the skill can be discovered.

## Update

If installed with the HTTPS clone command above:

```bash
cd "$HOME/.codex/skills/trello-project-workflow"
git pull
```

Start a new Codex session after updating if the current session does not pick up the changed skill.

## Trello Credentials

Create Trello credentials from <https://trello.com/app-key>:

1. Copy the API key into `TRELLO_KEY`.
2. Click the token link beside the key.
3. Authorize access.
4. Copy the generated token into `TRELLO_TOKEN`.

Set credentials in the shell or environment that starts Codex:

```bash
export TRELLO_KEY="your_api_key"
export TRELLO_TOKEN="your_generated_token"
```

Do not commit credentials into a project repository.

## Project Configuration

Each project should have a local `.codex/trello.json`:

```json
{
  "board": {
    "name": "Example Board",
    "idOrShortLink": "8M3BYzc0"
  },
  "lists": {
    "start": "In Progress",
    "implemented": "Dev Ready",
    "verified": "In Staging/Verification",
    "incomingBugs": "Capture.dev Bug Reports",
    "done": "Completed/Done"
  },
  "cardDefaults": {
    "prefix": "v2",
    "position": "top"
  }
}
```

The board short link comes from Trello board URLs such as:

```text
https://trello.com/b/8M3BYzc0/example-board
```

In this example, `8M3BYzc0` is the board short link.

## Initialize Config

Preview a project config without writing:

```bash
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" init-config \
  --board-url "https://trello.com/b/8M3BYzc0/example-board" \
  --board-name "Example Board" \
  --start-list "In Progress" \
  --implemented-list "Dev Ready" \
  --verified-list "In Staging/Verification"
```

Write it after checking the preview:

```bash
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" init-config \
  --board-url "https://trello.com/b/8M3BYzc0/example-board" \
  --board-name "Example Board" \
  --start-list "In Progress" \
  --implemented-list "Dev Ready" \
  --verified-list "In Staging/Verification" \
  --write
```

Existing config files are not overwritten unless `--force` is explicitly passed.

## Verify

From a configured project:

```bash
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" config-check
```

## Common Commands

```bash
python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" create \
  --title "Task title" \
  --desc "Short task context" \
  --list-key start

python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" resume \
  --card "https://trello.com/c/abc123/card-name"

python "$HOME/.codex/skills/trello-project-workflow/scripts/trello_project.py" finish \
  --card "https://trello.com/c/abc123/card-name" \
  --overview "Updated workflow rules and validated helper dry-runs."
```

Use `--dry-run` on mutating commands to preview intent without changing Trello.

## Safety

The helper intentionally supports only read, create, move, and comment operations. It does not delete, archive, close, or bulk edit Trello cards.
