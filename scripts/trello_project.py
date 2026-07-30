#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = 'https://api.trello.com/1'

DEFAULT_CARD_PREFIX = ''
DEFAULT_CARD_POSITION = 'top'


class TrelloError(Exception):
    pass


def find_project_config(start):
    current = Path(start).resolve()
    for candidate in [current, *current.parents]:
        config_path = candidate / '.codex' / 'trello.json'
        if config_path.exists():
            return config_path
    raise TrelloError('Missing project Trello config: .codex/trello.json')


def load_config(start):
    config_path = find_project_config(start)
    with config_path.open('r', encoding='utf-8') as handle:
        config = json.load(handle)
    return config_path, config


def parse_board_id(value):
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if parsed.netloc and 'trello.com' in parsed.netloc:
        bits = [bit for bit in parsed.path.split('/') if bit]
        if len(bits) >= 2 and bits[0] == 'b':
            return bits[1]
    return value


def parse_list_mapping(values):
    result = {}
    for value in values or []:
        if '=' not in value:
            raise TrelloError(f'Invalid --list value "{value}". Expected KEY=NAME.')
        key, name = value.split('=', 1)
        key = key.strip()
        name = name.strip()
        if not key or not name:
            raise TrelloError(f'Invalid --list value "{value}". Expected non-empty KEY=NAME.')
        result[key] = name
    return result


def output_config_path(cwd, output):
    if output:
        path = Path(output)
        if not path.is_absolute():
            path = Path(cwd).resolve() / path
        return path
    return Path(cwd).resolve() / '.codex' / 'trello.json'


def require_credentials():
    key = os.environ.get('TRELLO_KEY')
    token = os.environ.get('TRELLO_TOKEN')
    if not key or not token:
        missing = []
        if not key:
            missing.append('TRELLO_KEY')
        if not token:
            missing.append('TRELLO_TOKEN')
        raise TrelloError('Missing Trello credential environment variable(s): ' + ', '.join(missing))
    return key, token


def request_json(method, path, params=None, data=None):
    key, token = require_credentials()
    all_params = dict(params or {})
    all_params['key'] = key
    all_params['token'] = token
    encoded_params = urllib.parse.urlencode(all_params)
    url = f'{API_BASE}{path}'
    if encoded_params:
        url = f'{url}?{encoded_params}'

    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode('utf-8')

    request = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode('utf-8')
    except urllib.error.HTTPError as err:
        detail = err.read().decode('utf-8', errors='replace')
        raise TrelloError(f'Trello API error {err.code}: {detail}') from err
    except urllib.error.URLError as err:
        raise TrelloError(f'Trello API connection error: {err.reason}') from err

    if not raw:
        return None
    return json.loads(raw)


def board_id(config):
    board = config.get('board') or {}
    value = board.get('idOrShortLink') or board.get('id')
    if not value:
        raise TrelloError('Missing board.idOrShortLink in .codex/trello.json')
    return value


def configured_lists(config):
    lists = config.get('lists')
    if not isinstance(lists, dict) or not lists:
        raise TrelloError('Missing lists mapping in .codex/trello.json')
    return lists


def configured_labels(config):
    labels = config.get('labels') or {}
    if not isinstance(labels, dict):
        raise TrelloError('Invalid labels mapping in .codex/trello.json; expected an object')
    return labels


def fetch_board_lists(config):
    return request_json('GET', f'/boards/{board_id(config)}/lists', {
        'fields': 'name,closed,pos',
        'filter': 'open'
    })


def resolve_lists(config):
    wanted = configured_lists(config)
    board_lists = fetch_board_lists(config)
    by_name = {item['name'].strip().lower(): item for item in board_lists}
    resolved = {}
    missing = {}
    for key, name in wanted.items():
        item = by_name.get(str(name).strip().lower())
        if item:
            resolved[key] = item
        else:
            missing[key] = name
    return resolved, missing, board_lists


def require_list(config, list_key):
    resolved, missing, _ = resolve_lists(config)
    if list_key in missing:
        raise TrelloError(f'Configured list "{list_key}" not found on board: {missing[list_key]}')
    if list_key not in resolved:
        raise TrelloError(f'List key "{list_key}" not configured in .codex/trello.json')
    return resolved[list_key]


def fetch_board_labels(config):
    return request_json('GET', f'/boards/{board_id(config)}/labels', {
        'fields': 'name,color',
        'limit': 1000
    })


def configured_label_name(config, label_ref):
    labels = configured_labels(config)
    return str(labels.get(label_ref, label_ref)).strip()


def resolve_label_from_items(config, label_ref, board_labels):
    wanted = configured_label_name(config, label_ref)
    if not wanted:
        raise TrelloError('Label name must not be empty')
    matches = [
        label for label in board_labels
        if str(label.get('name') or '').strip().lower() == wanted.lower()
    ]
    if not matches:
        raise TrelloError(f'Label "{label_ref}" not found on board (resolved name: {wanted})')
    if len(matches) > 1:
        raise TrelloError(f'Label name is ambiguous on board: {wanted}')
    return matches[0]


def require_label(config, label_ref, board_labels=None):
    items = board_labels if board_labels is not None else fetch_board_labels(config)
    return resolve_label_from_items(config, label_ref, items)


def resolve_configured_labels(config, board_labels=None):
    if not configured_labels(config) and board_labels is None:
        return {}, {}, []
    items = board_labels if board_labels is not None else fetch_board_labels(config)
    resolved = {}
    missing = {}
    for key, name in configured_labels(config).items():
        try:
            resolved[key] = resolve_label_from_items(config, key, items)
        except TrelloError:
            missing[key] = name
    return resolved, missing, items


def configured_list_name(config, list_key):
    lists = configured_lists(config)
    if list_key not in lists:
        raise TrelloError(f'List key "{list_key}" not configured in .codex/trello.json')
    return lists[list_key]


def normalize_label(label):
    return {
        'id': label.get('id'),
        'name': label.get('name'),
        'color': label.get('color')
    }


def normalize_member(member):
    return {
        'id': member.get('id'),
        'username': member.get('username'),
        'fullName': member.get('fullName')
    }


def normalize_card_summary(card):
    return {
        'id': card['id'],
        'shortLink': card.get('shortLink'),
        'name': card.get('name'),
        'url': card.get('url'),
        'dateLastActivity': card.get('dateLastActivity'),
        'idList': card.get('idList'),
        'pos': card.get('pos'),
        'labels': [normalize_label(label) for label in card.get('labels', [])],
        'idMembers': card.get('idMembers', [])
    }


def card_matches_label_ids(card, required, excluded):
    present = set(card.get('idLabels') or [])
    return (
        {label['id'] for label in required}.issubset(present)
        and present.isdisjoint({label['id'] for label in excluded})
    )


def fetch_list_cards(trello_list):
    cards = request_json('GET', f'/lists/{trello_list["id"]}/cards', {
        'fields': 'name,desc,url,shortLink,dateLastActivity,idList,closed,pos,idLabels,idMembers',
        'labels': 'all',
        'filter': 'open'
    })
    return sorted(cards, key=lambda card: (card.get('pos', float('inf')), card.get('id', '')))


def fetch_card_state(card_id):
    return request_json('GET', f'/cards/{card_id}', {
        'fields': 'name,desc,url,shortLink,dateLastActivity,idList,closed,pos,idLabels,idMembers',
        'labels': 'all'
    })


def strip_named_prefix(value, prefix):
    marker = f'{prefix}:'
    if prefix and value.lower().startswith(marker.lower()):
        return value[len(marker):].strip()
    return value


def card_name_with_configured_prefix(title, prefix):
    name = title.strip()
    prefix = (prefix or '').strip()

    if prefix:
        name = strip_named_prefix(name, prefix)
        if prefix.lower() != 'codex':
            name = strip_named_prefix(name, 'Codex')
        return f'{prefix}: {name}'

    return strip_named_prefix(name, 'Codex')


def normalize_card_id(card):
    if 'trello.com/c/' in card:
        parts = urllib.parse.urlparse(card)
        bits = [bit for bit in parts.path.split('/') if bit]
        if len(bits) >= 2 and bits[0] == 'c':
            return bits[1]
    return card


def print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def move_card_to_list(config, card_id, list_key, pos):
    trello_list = require_list(config, list_key)
    payload = {
        'idList': trello_list['id'],
        'pos': pos
    }
    card = request_json('PUT', f'/cards/{card_id}', data=payload)
    return card, trello_list


def add_card_comment(card_id, text):
    return request_json('POST', f'/cards/{card_id}/actions/comments', data={'text': text})


def command_config_check(args):
    config_path, config = load_config(args.cwd)
    require_credentials()
    resolved, missing, _ = resolve_lists(config)
    resolved_labels, missing_labels, _ = resolve_configured_labels(config)
    result = {
        'ok': not missing and not missing_labels,
        'configPath': str(config_path),
        'board': config.get('board'),
        'resolvedLists': {
            key: {
                'id': item['id'],
                'name': item['name']
            }
            for key, item in resolved.items()
        },
        'missingLists': missing,
        'resolvedLabels': {
            key: normalize_label(item)
            for key, item in resolved_labels.items()
        },
        'missingLabels': missing_labels
    }
    print_json(result)
    return 0 if not missing and not missing_labels else 2


def command_init_config(args):
    board_value = parse_board_id(args.board_url or args.board_id)
    if not board_value:
        raise TrelloError('Missing --board-url or --board-id.')

    lists = {}
    if args.start_list:
        lists['start'] = args.start_list
    if args.implemented_list:
        lists['implemented'] = args.implemented_list
    if args.verified_list:
        lists['verified'] = args.verified_list
    if args.incoming_bugs_list:
        lists['incomingBugs'] = args.incoming_bugs_list
    if args.done_list:
        lists['done'] = args.done_list
    lists.update(parse_list_mapping(args.list))
    labels = parse_list_mapping(args.label)

    if not lists:
        raise TrelloError('Missing list mapping. Provide --start-list/--implemented-list/--verified-list or --list KEY=NAME.')

    config = {
        'board': {
            'name': args.board_name or '',
            'idOrShortLink': board_value
        },
        'lists': lists,
        'cardDefaults': {
            'prefix': args.prefix,
            'position': args.position
        }
    }
    if labels:
        config['labels'] = labels

    target = output_config_path(args.cwd, args.output)
    if not args.write:
        print_json({
            'dryRun': True,
            'target': str(target),
            'config': config
        })
        return 0

    if target.exists() and not args.force:
        raise TrelloError(f'Config already exists: {target}. Pass --force only if the user explicitly approved overwrite.')

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8') as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    print_json({
        'ok': True,
        'target': str(target),
        'config': config
    })
    return 0


def command_lists(args):
    _, config = load_config(args.cwd)
    resolved, missing, board_lists = resolve_lists(config)
    result = {
        'configured': {
            key: {
                'id': item['id'],
                'name': item['name']
            }
            for key, item in resolved.items()
        },
        'missing': missing,
        'boardLists': [
            {
                'id': item['id'],
                'name': item['name']
            }
            for item in board_lists
        ]
    }
    print_json(result)
    return 0 if not missing else 2


def command_labels(args):
    _, config = load_config(args.cwd)
    board_labels = fetch_board_labels(config)
    resolved, missing, _ = resolve_configured_labels(config, board_labels)
    result = {
        'configured': {
            key: normalize_label(item)
            for key, item in resolved.items()
        },
        'missing': missing,
        'boardLabels': [normalize_label(label) for label in board_labels]
    }
    print_json(result)
    return 0 if not missing else 2


def command_cards(args):
    _, config = load_config(args.cwd)
    trello_list = require_list(config, args.list_key)
    cards = fetch_list_cards(trello_list)
    print_json([normalize_card_summary(card) for card in cards])
    return 0


def command_next_card(args):
    _, config = load_config(args.cwd)
    trello_list = require_list(config, args.list_key)
    cards = fetch_list_cards(trello_list)
    board_labels = fetch_board_labels(config) if args.require_label or args.exclude_label else []
    required = [require_label(config, ref, board_labels) for ref in args.require_label]
    excluded = [require_label(config, ref, board_labels) for ref in args.exclude_label]
    matches = [
        card for card in cards
        if card_matches_label_ids(card, required, excluded)
    ]
    print_json(normalize_card_summary(matches[0]) if matches else None)
    return 0


def command_card(args):
    load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    card = request_json('GET', f'/cards/{card_id}', {
        'fields': 'name,desc,url,shortLink,dateLastActivity,idList,closed',
        'attachments': 'true',
        'attachment_fields': 'name,url,date,mimeType'
    })
    print_json({
        'id': card['id'],
        'shortLink': card.get('shortLink'),
        'name': card.get('name'),
        'desc': card.get('desc'),
        'url': card.get('url'),
        'dateLastActivity': card.get('dateLastActivity'),
        'idList': card.get('idList'),
        'attachments': [
            {
                'id': attachment.get('id'),
                'name': attachment.get('name'),
                'url': attachment.get('url'),
                'date': attachment.get('date'),
                'mimeType': attachment.get('mimeType')
            }
            for attachment in card.get('attachments', [])
        ]
    })
    return 0


def normalize_action(action):
    member = action.get('memberCreator') or {}
    return {
        'id': action.get('id'),
        'type': action.get('type'),
        'date': action.get('date'),
        'memberCreator': normalize_member(member) if member else None,
        'data': action.get('data') or {}
    }


def fetch_card_actions(card_id, actions_limit):
    common = {
        'memberCreator': 'true',
        'memberCreator_fields': 'fullName,username'
    }
    recent = request_json('GET', f'/cards/{card_id}/actions', {
        **common,
        'filter': 'commentCard,updateCard:idList,addLabelToCard,removeLabelFromCard',
        'limit': actions_limit
    })
    created = request_json('GET', f'/cards/{card_id}/actions', {
        **common,
        'filter': 'createCard',
        'limit': 1
    })
    by_id = {
        action.get('id'): action
        for action in [*(recent or []), *(created or [])]
        if action.get('id')
    }
    return sorted(by_id.values(), key=lambda action: action.get('date') or '')


def command_card_context(args):
    _, config = load_config(args.cwd)
    if args.actions_limit < 1 or args.actions_limit > 1000:
        raise TrelloError('--actions-limit must be between 1 and 1000')
    card_id = normalize_card_id(args.card)
    card = request_json('GET', f'/cards/{card_id}', {
        'fields': 'name,desc,url,shortLink,dateLastActivity,idList,closed,pos,idLabels,idMembers',
        'attachments': 'true',
        'attachment_fields': 'name,url,date,mimeType',
        'labels': 'all',
        'members': 'true',
        'member_fields': 'fullName,username',
        'checklists': 'all',
        'checklist_fields': 'name,pos',
        'checkItem_fields': 'name,state,pos'
    })
    actions = fetch_card_actions(card_id, args.actions_limit)
    creator_action = next((action for action in actions if action.get('type') == 'createCard'), None)
    board_lists = fetch_board_lists(config)
    list_by_id = {item['id']: item['name'] for item in board_lists}
    result = {
        **normalize_card_summary(card),
        'desc': card.get('desc'),
        'closed': card.get('closed'),
        'list': {
            'id': card.get('idList'),
            'name': list_by_id.get(card.get('idList'))
        },
        'creator': (
            normalize_member(creator_action.get('memberCreator') or {})
            if creator_action else None
        ),
        'members': [normalize_member(member) for member in card.get('members', [])],
        'attachments': [
            {
                'id': attachment.get('id'),
                'name': attachment.get('name'),
                'url': attachment.get('url'),
                'date': attachment.get('date'),
                'mimeType': attachment.get('mimeType')
            }
            for attachment in card.get('attachments', [])
        ],
        'checklists': [
            {
                'id': checklist.get('id'),
                'name': checklist.get('name'),
                'pos': checklist.get('pos'),
                'items': [
                    {
                        'id': item.get('id'),
                        'name': item.get('name'),
                        'state': item.get('state'),
                        'pos': item.get('pos')
                    }
                    for item in sorted(
                        checklist.get('checkItems', []),
                        key=lambda value: value.get('pos', float('inf'))
                    )
                ]
            }
            for checklist in sorted(
                card.get('checklists', []),
                key=lambda value: value.get('pos', float('inf'))
            )
        ],
        'actions': [normalize_action(action) for action in actions]
    }
    print_json(result)
    return 0


def command_create(args):
    _, config = load_config(args.cwd)
    defaults = config.get('cardDefaults') or {}
    pos = args.pos or defaults.get('position') or 'top'
    name = card_name_with_configured_prefix(args.title, defaults.get('prefix'))
    if args.dry_run:
        list_name = configured_list_name(config, args.list_key)
        print_json({
            'dryRun': True,
            'operation': 'create',
            'list': {
                'key': args.list_key,
                'name': list_name
            },
            'payload': {
                'name': name,
                'desc': args.desc or '',
                'pos': pos
            }
        })
        return 0
    trello_list = require_list(config, args.list_key)
    payload = {
        'idList': trello_list['id'],
        'name': name,
        'desc': args.desc or '',
        'pos': pos
    }
    card = request_json('POST', '/cards', data=payload)
    print_json({
        'id': card['id'],
        'shortLink': card.get('shortLink'),
        'name': card.get('name'),
        'url': card.get('url')
    })
    return 0


def command_move(args):
    _, config = load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    pos = args.pos or DEFAULT_CARD_POSITION
    if args.dry_run:
        list_name = configured_list_name(config, args.to)
        print_json({
            'dryRun': True,
            'operation': 'move',
            'card': card_id,
            'pos': pos,
            'comment': args.comment,
            'to': {
                'key': args.to,
                'name': list_name
            }
        })
        return 0
    card, trello_list = move_card_to_list(config, card_id, args.to, pos)
    result = {
        'id': card['id'],
        'name': card.get('name'),
        'url': card.get('url'),
        'idList': card.get('idList'),
        'list': {
            'key': args.to,
            'id': trello_list['id'],
            'name': trello_list['name']
        }
    }
    if args.comment:
        action = add_card_comment(card_id, args.comment)
        result['comment'] = {
            'id': action['id'],
            'type': action.get('type'),
            'date': action.get('date')
        }
    print_json(result)
    return 0


def command_comment(args):
    load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    payload = {
        'text': args.text
    }
    if args.dry_run:
        print_json({
            'dryRun': True,
            'operation': 'comment',
            'card': card_id,
            'text': args.text
        })
        return 0
    action = add_card_comment(card_id, args.text)
    print_json({
        'id': action['id'],
        'type': action.get('type'),
        'date': action.get('date')
    })
    return 0


def command_whoami(args):
    load_config(args.cwd)
    member = request_json('GET', '/members/me', {
        'fields': 'username,fullName,url'
    })
    print_json({
        **normalize_member(member),
        'url': member.get('url')
    })
    return 0


def command_change_label(args, add):
    _, config = load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    card = fetch_card_state(card_id)
    label = require_label(config, args.label)
    present = label['id'] in (card.get('idLabels') or [])
    changed = (add and not present) or (not add and present)
    operation = 'add-label' if add else 'remove-label'

    if args.dry_run:
        print_json({
            'dryRun': True,
            'operation': operation,
            'card': normalize_card_summary(card),
            'label': normalize_label(label),
            'wouldChange': changed
        })
        return 0

    if changed:
        if add:
            request_json('POST', f'/cards/{card_id}/idLabels', data={'value': label['id']})
        else:
            request_json('DELETE', f'/cards/{card_id}/idLabels/{label["id"]}')
    print_json({
        'operation': operation,
        'card': card_id,
        'label': normalize_label(label),
        'changed': changed
    })
    return 0


def command_add_label(args):
    return command_change_label(args, True)


def command_remove_label(args):
    return command_change_label(args, False)


def command_claim(args):
    _, config = load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    source_list = require_list(config, args.from_list)
    target_list = require_list(config, args.to)
    card = fetch_card_state(card_id)

    if card.get('closed'):
        raise TrelloError('Cannot claim a closed card')
    already_in_target = card.get('idList') == target_list['id']
    if not already_in_target and card.get('idList') != source_list['id']:
        raise TrelloError(
            f'Claim rejected: card is not in configured source list "{args.from_list}" '
            f'({source_list["name"]})'
        )
    if (
        not already_in_target
        and args.expected_last_activity
        and card.get('dateLastActivity') != args.expected_last_activity
    ):
        raise TrelloError(
            'Claim rejected: card changed after selection '
            f'(expected {args.expected_last_activity}, found {card.get("dateLastActivity")})'
        )

    board_labels = fetch_board_labels(config)
    required = [require_label(config, ref, board_labels) for ref in args.require_label]
    excluded = [require_label(config, ref, board_labels) for ref in args.exclude_label]
    add_labels = [require_label(config, ref, board_labels) for ref in args.add_label]
    remove_labels = [require_label(config, ref, board_labels) for ref in args.remove_label]
    present_ids = set(card.get('idLabels') or [])

    if not already_in_target:
        missing_required = [label['name'] for label in required if label['id'] not in present_ids]
        present_excluded = [label['name'] for label in excluded if label['id'] in present_ids]
        if missing_required:
            raise TrelloError('Claim rejected: missing required label(s): ' + ', '.join(missing_required))
        if present_excluded:
            raise TrelloError('Claim rejected: excluded label(s) present: ' + ', '.join(present_excluded))

    add_ids = {label['id'] for label in add_labels}
    remove_ids = {label['id'] for label in remove_labels}
    overlap = add_ids & remove_ids
    if overlap:
        names = [label['name'] for label in add_labels if label['id'] in overlap]
        raise TrelloError('Cannot add and remove the same label(s): ' + ', '.join(names))

    preview = {
        'operation': 'claim',
        'card': normalize_card_summary(card),
        'from': {'key': args.from_list, 'id': source_list['id'], 'name': source_list['name']},
        'to': {'key': args.to, 'id': target_list['id'], 'name': target_list['name']},
        'pos': args.pos,
        'requiredLabels': [normalize_label(label) for label in required],
        'excludedLabels': [normalize_label(label) for label in excluded],
        'addLabels': [normalize_label(label) for label in add_labels],
        'removeLabels': [normalize_label(label) for label in remove_labels],
        'comment': args.comment,
        'alreadyInTarget': already_in_target
    }
    if args.dry_run:
        print_json({'dryRun': True, **preview})
        return 0

    moved = card
    if not already_in_target:
        moved = request_json('PUT', f'/cards/{card_id}', data={
            'idList': target_list['id'],
            'pos': args.pos
        })
    changed_labels = []
    for label in add_labels:
        if label['id'] not in present_ids:
            request_json('POST', f'/cards/{card_id}/idLabels', data={'value': label['id']})
            changed_labels.append({'operation': 'add', **normalize_label(label)})
    for label in remove_labels:
        if label['id'] in present_ids:
            request_json('DELETE', f'/cards/{card_id}/idLabels/{label["id"]}')
            changed_labels.append({'operation': 'remove', **normalize_label(label)})
    # A retried claim may finish interrupted label changes, but must not duplicate
    # the original claim comment.
    comment_action = (
        add_card_comment(card_id, args.comment)
        if args.comment and not already_in_target else None
    )

    result = {
        'claimed': not already_in_target,
        'reason': 'already_in_target' if already_in_target else 'moved',
        **preview,
        'card': {
            'id': moved.get('id', card_id),
            'name': moved.get('name', card.get('name')),
            'url': moved.get('url', card.get('url')),
            'idList': moved.get('idList', target_list['id'])
        },
        'changedLabels': changed_labels
    }
    if comment_action:
        result['commentAction'] = {
            'id': comment_action.get('id'),
            'type': comment_action.get('type'),
            'date': comment_action.get('date')
        }
    print_json(result)
    return 0


def command_resume(args):
    _, config = load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    pos = args.pos or DEFAULT_CARD_POSITION
    text = args.text or 'Work resumed: continuing implementation on this task.'
    if args.dry_run:
        list_name = configured_list_name(config, 'start')
        print_json({
            'dryRun': True,
            'operation': 'resume',
            'card': card_id,
            'pos': pos,
            'to': {
                'key': 'start',
                'name': list_name
            },
            'comment': text
        })
        return 0
    card, trello_list = move_card_to_list(config, card_id, 'start', pos)
    action = add_card_comment(card_id, text)
    print_json({
        'id': card['id'],
        'name': card.get('name'),
        'url': card.get('url'),
        'idList': card.get('idList'),
        'list': {
            'key': 'start',
            'id': trello_list['id'],
            'name': trello_list['name']
        },
        'comment': {
            'id': action['id'],
            'type': action.get('type'),
            'date': action.get('date')
        }
    })
    return 0


def command_finish(args):
    _, config = load_config(args.cwd)
    card_id = normalize_card_id(args.card)
    pos = args.pos or DEFAULT_CARD_POSITION
    overview = args.overview.strip()
    if not overview:
        raise TrelloError('Missing non-empty --overview.')
    text = overview
    if not text.lower().startswith('implemented:'):
        text = f'Implemented: {text}'
    if args.dry_run:
        list_name = configured_list_name(config, args.to)
        print_json({
            'dryRun': True,
            'operation': 'finish',
            'card': card_id,
            'pos': pos,
            'to': {
                'key': args.to,
                'name': list_name
            },
            'comment': text
        })
        return 0
    card, trello_list = move_card_to_list(config, card_id, args.to, pos)
    action = add_card_comment(card_id, text)
    print_json({
        'id': card['id'],
        'name': card.get('name'),
        'url': card.get('url'),
        'idList': card.get('idList'),
        'list': {
            'key': args.to,
            'id': trello_list['id'],
            'name': trello_list['name']
        },
        'comment': {
            'id': action['id'],
            'type': action.get('type'),
            'date': action.get('date')
        }
    })
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description='Manage project Trello workflow cards.')
    parser.add_argument('--cwd', default=os.getcwd(), help='Project directory used to find .codex/trello.json.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    config_check = subparsers.add_parser('config-check')
    config_check.set_defaults(func=command_config_check)

    init_config = subparsers.add_parser('init-config')
    init_config.add_argument('--board-url')
    init_config.add_argument('--board-id')
    init_config.add_argument('--board-name')
    init_config.add_argument('--start-list')
    init_config.add_argument('--implemented-list')
    init_config.add_argument('--verified-list')
    init_config.add_argument('--incoming-bugs-list')
    init_config.add_argument('--done-list')
    init_config.add_argument('--list', action='append', default=[], help='Additional or overriding semantic list mapping as KEY=NAME.')
    init_config.add_argument('--label', action='append', default=[], help='Semantic label mapping as KEY=NAME.')
    init_config.add_argument('--prefix', default=DEFAULT_CARD_PREFIX)
    init_config.add_argument('--position', default=DEFAULT_CARD_POSITION)
    init_config.add_argument('--output')
    init_config.add_argument('--write', action='store_true')
    init_config.add_argument('--force', action='store_true')
    init_config.set_defaults(func=command_init_config)

    lists = subparsers.add_parser('lists')
    lists.set_defaults(func=command_lists)

    labels = subparsers.add_parser('labels')
    labels.set_defaults(func=command_labels)

    cards = subparsers.add_parser('cards')
    cards.add_argument('--list-key', required=True)
    cards.set_defaults(func=command_cards)

    next_card = subparsers.add_parser('next-card')
    next_card.add_argument('--list-key', required=True)
    next_card.add_argument('--require-label', action='append', default=[])
    next_card.add_argument('--exclude-label', action='append', default=[])
    next_card.set_defaults(func=command_next_card)

    card = subparsers.add_parser('card')
    card.add_argument('--card', required=True)
    card.set_defaults(func=command_card)

    card_context = subparsers.add_parser('card-context')
    card_context.add_argument('--card', required=True)
    card_context.add_argument('--actions-limit', type=int, default=100)
    card_context.set_defaults(func=command_card_context)

    whoami = subparsers.add_parser('whoami')
    whoami.set_defaults(func=command_whoami)

    create = subparsers.add_parser('create')
    create.add_argument('--title', required=True)
    create.add_argument('--desc', default='')
    create.add_argument('--list-key', default='start')
    create.add_argument('--pos')
    create.add_argument('--dry-run', action='store_true')
    create.set_defaults(func=command_create)

    move = subparsers.add_parser('move')
    move.add_argument('--card', required=True)
    move.add_argument('--to', required=True)
    move.add_argument('--pos', default=DEFAULT_CARD_POSITION)
    move.add_argument('--comment')
    move.add_argument('--dry-run', action='store_true')
    move.set_defaults(func=command_move)

    comment = subparsers.add_parser('comment')
    comment.add_argument('--card', required=True)
    comment.add_argument('--text', required=True)
    comment.add_argument('--dry-run', action='store_true')
    comment.set_defaults(func=command_comment)

    add_label = subparsers.add_parser('add-label')
    add_label.add_argument('--card', required=True)
    add_label.add_argument('--label', required=True)
    add_label.add_argument('--dry-run', action='store_true')
    add_label.set_defaults(func=command_add_label)

    remove_label = subparsers.add_parser('remove-label')
    remove_label.add_argument('--card', required=True)
    remove_label.add_argument('--label', required=True)
    remove_label.add_argument('--dry-run', action='store_true')
    remove_label.set_defaults(func=command_remove_label)

    claim = subparsers.add_parser('claim')
    claim.add_argument('--card', required=True)
    claim.add_argument('--from', dest='from_list', required=True)
    claim.add_argument('--to', required=True)
    claim.add_argument('--expected-last-activity')
    claim.add_argument('--require-label', action='append', default=[])
    claim.add_argument('--exclude-label', action='append', default=[])
    claim.add_argument('--add-label', action='append', default=[])
    claim.add_argument('--remove-label', action='append', default=[])
    claim.add_argument('--comment')
    claim.add_argument('--pos', default=DEFAULT_CARD_POSITION)
    claim.add_argument('--dry-run', action='store_true')
    claim.set_defaults(func=command_claim)

    resume = subparsers.add_parser('resume')
    resume.add_argument('--card', required=True)
    resume.add_argument('--text')
    resume.add_argument('--pos', default=DEFAULT_CARD_POSITION)
    resume.add_argument('--dry-run', action='store_true')
    resume.set_defaults(func=command_resume)

    finish = subparsers.add_parser('finish')
    finish.add_argument('--card', required=True)
    finish.add_argument('--overview', required=True)
    finish.add_argument('--to', default='implemented')
    finish.add_argument('--pos', default=DEFAULT_CARD_POSITION)
    finish.add_argument('--dry-run', action='store_true')
    finish.set_defaults(func=command_finish)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except TrelloError as err:
        print(f'Error: {err}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
