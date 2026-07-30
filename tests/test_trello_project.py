import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'trello_project.py'
SPEC = importlib.util.spec_from_file_location('trello_project', SCRIPT)
trello = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trello)


def args(**values):
    return argparse.Namespace(**values)


def run_and_parse(function, namespace):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = function(namespace)
    return status, json.loads(output.getvalue())


class TrelloProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.temp.name)
        config_dir = self.cwd / '.codex'
        config_dir.mkdir()
        self.config = {
            'board': {'name': 'Test', 'idOrShortLink': 'board'},
            'lists': {
                'backlog': 'Round Backlog',
                'analyzed': 'Analyzed',
                'start': 'In Progress'
            },
            'labels': {
                'aiReady': 'AI Ready',
                'aiManaged': 'AI Managed',
                'aiNeedsInput': 'AI Needs Input',
                'aiHold': 'AI Hold'
            },
            'cardDefaults': {'prefix': 'v3', 'position': 'top'}
        }
        (config_dir / 'trello.json').write_text(json.dumps(self.config), encoding='utf-8')
        self.board_lists = [
            {'id': 'L1', 'name': 'Round Backlog', 'closed': False, 'pos': 1},
            {'id': 'L2', 'name': 'Analyzed', 'closed': False, 'pos': 2},
            {'id': 'L3', 'name': 'In Progress', 'closed': False, 'pos': 3}
        ]
        self.board_labels = [
            {'id': 'R', 'name': 'AI Ready', 'color': 'green'},
            {'id': 'M', 'name': 'AI Managed', 'color': 'blue'},
            {'id': 'N', 'name': 'AI Needs Input', 'color': 'yellow'},
            {'id': 'H', 'name': 'AI Hold', 'color': 'red'}
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_init_config_writes_one_valid_document_with_labels(self):
        target = self.cwd / 'generated.json'
        namespace = args(
            cwd=str(self.cwd), board_url=None, board_id='board', board_name='Test',
            start_list='In Progress', implemented_list=None, verified_list=None,
            incoming_bugs_list=None, done_list=None,
            list=['analyzed=Analyzed'], label=['aiReady=AI Ready'],
            prefix='v3', position='top', output=str(target), write=True, force=False
        )
        status, result = run_and_parse(trello.command_init_config, namespace)
        self.assertEqual(status, 0)
        parsed = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(parsed['labels']['aiReady'], 'AI Ready')
        self.assertEqual(result['config'], parsed)

    def test_next_card_preserves_priority_and_applies_semantic_labels(self):
        cards = [
            {
                'id': 'lower', 'name': 'Lower', 'pos': 200, 'idList': 'L1',
                'labels': [{'id': 'R', 'name': 'AI Ready', 'color': 'green'}],
                'idLabels': ['R'], 'idMembers': []
            },
            {
                'id': 'held', 'name': 'Held', 'pos': 50, 'idList': 'L1',
                'labels': [
                    {'id': 'R', 'name': 'AI Ready', 'color': 'green'},
                    {'id': 'H', 'name': 'AI Hold', 'color': 'red'}
                ],
                'idLabels': ['R', 'H'], 'idMembers': []
            },
            {
                'id': 'top', 'name': 'Top eligible', 'pos': 100, 'idList': 'L1',
                'labels': [{'id': 'R', 'name': 'AI Ready', 'color': 'green'}],
                'idLabels': ['R'], 'idMembers': []
            }
        ]

        def request(_method, path, _params=None, data=None):
            self.assertIsNone(data)
            if path == '/boards/board/lists':
                return self.board_lists
            if path == '/lists/L1/cards':
                return cards
            if path == '/boards/board/labels':
                return self.board_labels
            self.fail(f'unexpected request: {path}')

        namespace = args(
            cwd=str(self.cwd), list_key='backlog',
            require_label=['aiReady'], exclude_label=['aiHold']
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_next_card, namespace)
        self.assertEqual(status, 0)
        self.assertEqual(result['id'], 'top')
        self.assertEqual(result['pos'], 100)

    def test_next_card_returns_null_when_no_card_matches(self):
        def request(_method, path, _params=None, data=None):
            if path == '/boards/board/lists':
                return self.board_lists
            if path == '/lists/L1/cards':
                return []
            if path == '/boards/board/labels':
                return self.board_labels
            self.fail(f'unexpected request: {path}')

        namespace = args(cwd=str(self.cwd), list_key='backlog', require_label=['aiReady'], exclude_label=[])
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_next_card, namespace)
        self.assertEqual(status, 0)
        self.assertIsNone(result)

    def test_add_label_is_idempotent(self):
        calls = []

        def request(method, path, params=None, data=None):
            calls.append((method, path, params, data))
            if path == '/cards/card':
                return {'id': 'card', 'idList': 'L1', 'idLabels': ['R'], 'labels': self.board_labels[:1]}
            if path == '/boards/board/labels':
                return self.board_labels
            self.fail(f'unexpected request: {path}')

        namespace = args(cwd=str(self.cwd), card='card', label='aiReady', dry_run=False)
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_add_label, namespace)
        self.assertEqual(status, 0)
        self.assertFalse(result['changed'])
        self.assertFalse(any(method == 'POST' for method, *_ in calls))

    def test_claim_dry_run_checks_source_labels_and_activity(self):
        card = {
            'id': 'card', 'name': 'Work', 'idList': 'L2', 'idLabels': ['M'],
            'labels': [{'id': 'M', 'name': 'AI Managed', 'color': 'blue'}],
            'dateLastActivity': '2026-07-30T10:00:00.000Z', 'pos': 10
        }

        def request(_method, path, _params=None, data=None):
            if path == '/boards/board/lists':
                return self.board_lists
            if path == '/cards/card':
                return card
            if path == '/boards/board/labels':
                return self.board_labels
            self.fail(f'unexpected request: {path}')

        namespace = args(
            cwd=str(self.cwd), card='card', from_list='analyzed', to='start',
            expected_last_activity=card['dateLastActivity'], require_label=['aiManaged'],
            exclude_label=['aiHold'], add_label=[], remove_label=[], comment='Claimed',
            pos='top', dry_run=True
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_claim, namespace)
        self.assertEqual(status, 0)
        self.assertTrue(result['dryRun'])
        self.assertEqual(result['from']['name'], 'Analyzed')
        self.assertEqual(result['to']['name'], 'In Progress')

    def test_claim_rejects_stale_selection(self):
        card = {
            'id': 'card', 'idList': 'L2', 'idLabels': ['M'], 'labels': [],
            'dateLastActivity': 'new'
        }

        def request(_method, path, _params=None, data=None):
            if path == '/boards/board/lists':
                return self.board_lists
            if path == '/cards/card':
                return card
            self.fail(f'unexpected request: {path}')

        namespace = args(
            cwd=str(self.cwd), card='card', from_list='analyzed', to='start',
            expected_last_activity='old', require_label=[], exclude_label=[], add_label=[],
            remove_label=[], comment=None, pos='top', dry_run=False
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            with self.assertRaisesRegex(trello.TrelloError, 'changed after selection'):
                trello.command_claim(namespace)

    def test_claim_moves_before_label_and_comment_mutations(self):
        card = {
            'id': 'card', 'name': 'Work', 'url': 'https://trello.test/card',
            'idList': 'L1', 'idLabels': ['R'],
            'labels': [{'id': 'R', 'name': 'AI Ready', 'color': 'green'}],
            'dateLastActivity': 'stamp', 'pos': 10
        }
        mutations = []

        def request(method, path, params=None, data=None):
            if method == 'GET' and path == '/boards/board/lists':
                return self.board_lists
            if method == 'GET' and path == '/cards/card':
                return card
            if method == 'GET' and path == '/boards/board/labels':
                return self.board_labels
            mutations.append((method, path, data))
            if method == 'PUT' and path == '/cards/card':
                return {**card, 'idList': 'L2'}
            if method == 'POST' and path.endswith('/actions/comments'):
                return {'id': 'comment', 'type': 'commentCard', 'date': 'later'}
            return {}

        namespace = args(
            cwd=str(self.cwd), card='card', from_list='backlog', to='analyzed',
            expected_last_activity='stamp', require_label=['aiReady'], exclude_label=['aiHold'],
            add_label=[], remove_label=['aiReady'], comment='Analysis complete',
            pos='top', dry_run=False
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_claim, namespace)
        self.assertEqual(status, 0)
        self.assertTrue(result['claimed'])
        self.assertEqual(mutations[0][:2], ('PUT', '/cards/card'))
        self.assertEqual(mutations[1][:2], ('DELETE', '/cards/card/idLabels/R'))
        self.assertEqual(mutations[2][:2], ('POST', '/cards/card/actions/comments'))

    def test_retried_claim_repairs_labels_without_duplicate_move_or_comment(self):
        card = {
            'id': 'card', 'name': 'Work', 'idList': 'L2', 'idLabels': ['R'],
            'labels': [{'id': 'R', 'name': 'AI Ready', 'color': 'green'}],
            'dateLastActivity': 'newer', 'pos': 10
        }
        mutations = []

        def request(method, path, params=None, data=None):
            if method == 'GET' and path == '/boards/board/lists':
                return self.board_lists
            if method == 'GET' and path == '/cards/card':
                return card
            if method == 'GET' and path == '/boards/board/labels':
                return self.board_labels
            if method == 'GET' and path == '/cards/card/actions':
                return [{'data': {'text': 'Do not duplicate'}}]
            mutations.append((method, path, data))
            return {}

        namespace = args(
            cwd=str(self.cwd), card='card', from_list='backlog', to='analyzed',
            expected_last_activity='old', require_label=['aiReady'], exclude_label=['aiHold'],
            add_label=[], remove_label=['aiReady'], comment='Do not duplicate',
            pos='top', dry_run=False
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_claim, namespace)
        self.assertEqual(status, 0)
        self.assertFalse(result['claimed'])
        self.assertEqual(result['reason'], 'already_in_target')
        self.assertTrue(result['commentAlreadyPresent'])
        self.assertEqual(mutations, [('DELETE', '/cards/card/idLabels/R', None)])

    def test_retried_claim_adds_missing_comment(self):
        card = {
            'id': 'card', 'name': 'Work', 'idList': 'L3', 'idLabels': ['M'],
            'labels': [{'id': 'M', 'name': 'AI Managed', 'color': 'blue'}],
            'dateLastActivity': 'newer', 'pos': 10
        }
        mutations = []

        def request(method, path, params=None, data=None):
            if method == 'GET' and path == '/boards/board/lists':
                return self.board_lists
            if method == 'GET' and path == '/cards/card':
                return card
            if method == 'GET' and path == '/boards/board/labels':
                return self.board_labels
            if method == 'GET' and path == '/cards/card/actions':
                return []
            mutations.append((method, path, data))
            if method == 'POST' and path.endswith('/actions/comments'):
                return {'id': 'comment', 'type': 'commentCard', 'date': 'later'}
            self.fail(f'unexpected request: {method} {path}')

        namespace = args(
            cwd=str(self.cwd), card='card', from_list='analyzed', to='start',
            expected_last_activity='old', require_label=['aiManaged'], exclude_label=['aiHold'],
            add_label=[], remove_label=[], comment='Claimed for implementation',
            pos='top', dry_run=False
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_claim, namespace)
        self.assertEqual(status, 0)
        self.assertFalse(result['claimed'])
        self.assertFalse(result['commentAlreadyPresent'])
        self.assertEqual(
            mutations,
            [('POST', '/cards/card/actions/comments', {'text': 'Claimed for implementation'})]
        )

    def test_retried_claim_still_rejects_excluded_label(self):
        card = {
            'id': 'card', 'name': 'Work', 'idList': 'L3', 'idLabels': ['M', 'H'],
            'labels': [
                {'id': 'M', 'name': 'AI Managed', 'color': 'blue'},
                {'id': 'H', 'name': 'AI Hold', 'color': 'red'}
            ],
            'dateLastActivity': 'newer', 'pos': 10
        }

        def request(_method, path, _params=None, data=None):
            if path == '/boards/board/lists':
                return self.board_lists
            if path == '/cards/card':
                return card
            if path == '/boards/board/labels':
                return self.board_labels
            self.fail(f'unexpected request: {path}')

        namespace = args(
            cwd=str(self.cwd), card='card', from_list='analyzed', to='start',
            expected_last_activity='old', require_label=['aiManaged'], exclude_label=['aiHold'],
            add_label=[], remove_label=[], comment='Claimed for implementation',
            pos='top', dry_run=False
        )
        with mock.patch.object(trello, 'request_json', side_effect=request):
            with self.assertRaisesRegex(trello.TrelloError, 'excluded label.*AI Hold'):
                trello.command_claim(namespace)

    def test_card_context_includes_creator_comments_and_sorted_checklists(self):
        card = {
            'id': 'card', 'name': 'Work', 'idList': 'L1', 'idLabels': [], 'labels': [],
            'idMembers': ['member'], 'members': [{'id': 'member', 'username': 'worker', 'fullName': 'Worker'}],
            'checklists': [{
                'id': 'check', 'name': 'Acceptance', 'pos': 1,
                'checkItems': [
                    {'id': 'second', 'name': 'Second', 'state': 'incomplete', 'pos': 2},
                    {'id': 'first', 'name': 'First', 'state': 'complete', 'pos': 1}
                ]
            }],
            'attachments': [], 'pos': 1, 'closed': False
        }
        creator = {'id': 'creator', 'username': 'alice', 'fullName': 'Alice'}

        def request(_method, path, params=None, data=None):
            if path == '/cards/card' and params.get('checklists') == 'all':
                return card
            if path == '/cards/card/actions' and params.get('filter') == 'createCard':
                return [{'id': 'created', 'type': 'createCard', 'date': '2026-01-01', 'memberCreator': creator, 'data': {}}]
            if path == '/cards/card/actions':
                return [{
                    'id': 'comment', 'type': 'commentCard', 'date': '2026-01-02',
                    'memberCreator': creator, 'data': {'text': 'Answer'}
                }]
            if path == '/boards/board/lists':
                return self.board_lists
            self.fail(f'unexpected request: {path}')

        namespace = args(cwd=str(self.cwd), card='card', actions_limit=100)
        with mock.patch.object(trello, 'request_json', side_effect=request):
            status, result = run_and_parse(trello.command_card_context, namespace)
        self.assertEqual(status, 0)
        self.assertEqual(result['creator']['username'], 'alice')
        self.assertEqual(result['checklists'][0]['items'][0]['name'], 'First')
        self.assertEqual([action['type'] for action in result['actions']], ['createCard', 'commentCard'])


if __name__ == '__main__':
    unittest.main()
