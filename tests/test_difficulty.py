import json
import pytest
from fastapi.testclient import TestClient
from backend import db
from backend.app import app
from backend.ai import difficulty as d, knowledge as k, recommendations as rec, service, vectors
from backend.ai.provider import Profile
from backend.identity import current_user

SKILL = 'math2.limit.expansion_order'

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path/'data')
    monkeypatch.setenv('MATHMASTER_AI_PROVIDER_FILE', str(tmp_path/'provider.json'))
    monkeypatch.setattr(vectors, 'ready', lambda p: False)
    with TestClient(app) as client:yield client


def question(client, level=3, topic='泰勒展开', confidence='high', subject='数学二'):
    qid = client.post('/api/questions', json={'text': '比较展开后的主导项', 'number': '1', 'subject': subject, 'confirmed': True}).json()['id']
    with db.connection() as c:q = k.bank_question(c, qid)
    payload = {'question_id': qid, 'question_text': q['text'], 'uncertain': False, 'has_diagram': False,
               'topic': topic, 'problem': {'skill_ids': [SKILL] if topic == '泰勒展开' else []},
               'methods': [], 'difficulty': {'level': level, 'confidence': confidence, 'reason': '需要判断适用条件与主导项', 'calculation_load': 'heavy'} if level else None}
    k.put(q, payload, 'fixture')
    return q


def outcome(q, result):
    with db.connection() as c:
        c.execute('INSERT OR REPLACE INTO difficulty_outcomes VALUES(?,?,?,?,?,?)',
                  (q['id'], 'fixture', k.fingerprint(q), json.dumps([SKILL]), result, d.now()))


def no_network(*a, **kw):pytest.fail('unexpected external model request')


def test_rating_is_versioned_and_personal_correction_is_user_owned(client):
    q = question(client)
    info = client.get('/api/questions/'+q['id']+'/difficulty').json()
    assert info['rating']['label'] == '标准' and info['rating']['calculation_load'] == 'heavy'
    guest = client.post('/api/users', json={'name': '难度用户'}).json()['id']
    # Registration changes the cookie; keep the first user explicit.
    assert client.put('/api/questions/'+q['id']+'/difficulty', headers={'X-MathMaster-User': 'zzy'},
                      json={'level': 4, 'fingerprint': info['rating']['fingerprint']}).status_code == 200
    assert client.get('/api/questions/'+q['id']+'/difficulty', headers={'X-MathMaster-User': guest}).json()['rating']['level'] == 3
    assert client.get('/api/questions/'+q['id']+'/difficulty', headers={'X-MathMaster-User': 'zzy'}).json()['rating']['level'] == 4
    with db.connection() as c:c.execute('UPDATE questions SET text=? WHERE id=?', ('改成另一道题', q['id']))
    assert client.get('/api/questions/'+q['id']+'/difficulty').json()['rating']['level'] is None
    assert client.put('/api/questions/'+q['id']+'/difficulty', json={'level': 2, 'fingerprint': info['rating']['fingerprint']}).status_code == 409


def test_assessment_does_not_default_unreadable_items_and_reuses_durable_ratings(client, monkeypatch):
    q = question(client, level=None)
    pending_id = client.post('/api/questions', json={'text': '请阅读下方原始题图', 'confirmed': False}).json()['id']
    with db.connection() as c:pending=k.bank_question(c,pending_id)
    calls = []
    monkeypatch.setattr('backend.ai.provider.load_profile', lambda: Profile(provider_name='fixture', base_url='https://fixture.invalid', model_id='fixture', api_key='x'))
    def request(profile, messages, **kw):
        items = json.loads(messages[-1]['content']);calls.append(items)
        assert profile.extra_body['max_tokens']>=6500
        assert '计算量' in messages[0]['content']
        value = {'items': [{'question_id': x['question_id'], 'level': 4, 'reason': '需要分类讨论', 'confidence': 'medium', 'calculation_load': 'light'} for x in items]}
        kw['validator'](json.dumps(value))
        return {'content': json.dumps(value), 'model_id': 'fixture'}
    d.assess([q, pending], request=request)
    assert len(calls) == 1 and len(calls[0]) == 1
    assert d.get(q)['level'] == 4
    d.assess([q], request=no_network)
    with db.connection() as c:c.execute('UPDATE questions SET text=? WHERE id=?', ('changed', q['id']))
    with db.connection() as c:changed = k.bank_question(c, q['id'])
    assert d.get(changed)['level'] is None


def test_difficulty_gate_scans_beyond_eight_and_never_falls_back_to_easy_or_unrelated(client, monkeypatch):
    source = question(client)
    easy = [question(client, 1) for _ in range(10)]
    harder = question(client, 4)
    unrelated = question(client, 4, topic='矩阵的秩')
    session = service.open_session(source['id'])
    items = [{'question_id': q['id'], 'score': .95-i*.004, 'reason': '同知识点', 'number': '1'} for i, q in enumerate(easy+[harder])]
    def search(**kw):assert kw['limit'] == 60;return {'items': items}
    monkeypatch.setattr(vectors, 'search', search)
    selected = rec.recommend(session, 'harder', no_network)
    assert selected['question_id'] == harder['id'] and selected['difficulty']['level'] == 4
    assert unrelated['id'] not in {x['question_id'] for x in selected['similar']}
    # A repeated recommendation is excluded, even though easy questions remain.
    gap = rec.recommend(session, 'harder', no_network)
    assert gap['question_id'] is None and gap['gap'] == 'no_matching_level'
    assert gap['target']['level'] == 4
    # The manual challenge becomes the training level; auto does not drop back.
    assert d.progression(source, k.get(source))['level'] == 4


def test_three_distinct_successes_promote_two_errors_remediate_and_keep_goal(client):
    current = question(client)
    for _ in range(3):outcome(question(client), 'independent')
    promoted = d.progression(current, k.get(current), update=True)
    assert promoted['level'] == 4
    assert d.progression(current, k.get(current), update=True)['level'] == 4
    for _ in range(2):outcome(question(client, 4), 'blocked')
    remedial = d.progression(current, k.get(current), update=True)
    assert remedial['level'] == 3 and remedial['goal_level'] == 4
    for _ in range(3):outcome(question(client), 'independent')
    assert d.progression(current, k.get(current), update=True)['level'] == 4


def test_hints_exposure_unverified_results_and_repeated_question_never_promote(client):
    q = question(client)
    for _ in range(4):
        outcome(q, 'independent');d.progression(q, k.get(q), update=True)
    assert d.progression(q, k.get(q))['level'] == 3
    for result in ('hinted', 'exposed', 'unverified'):
        outcome(question(client), result)
    value = d.progression(q, k.get(q), update=True)
    assert value['level'] == 3 and value['successes'] == 0


def test_outcome_recording_distinguishes_calculation_hint_and_prior_exposure(client):
    q = question(client)
    def record(previous, state):
        with db.connection() as c:d.record(c, q, {'id': 'session', 'state': json.dumps(previous)}, state)
        with db.connection() as c:return dict(c.execute('SELECT * FROM difficulty_outcomes WHERE question_id=?', (q['id'],)).fetchone())
    # A delegated computation cannot turn a spurious needs_hint observation into assistance.
    previous = {'difficulty_reasoned': True, 'hint_level': 0}
    state = {'last_intent': 'calculate', 'hint_level': 0, 'last_action': 'complete', 'completion_check': 'valid',
             'final_answer_current_turn': True, 'skill_ids': [SKILL], 'observations': [{'judgement': 'needs_hint'}]}
    assert record(previous, state)['outcome'] == 'independent'
    # Prior answer exposure is not independent completion.
    with db.connection() as c:c.execute('DELETE FROM difficulty_outcomes')
    assert record({'answer_exposed': True}, state)['outcome'] == 'exposed'
    # A genuine conceptual hint keeps the result at the current level.
    with db.connection() as c:c.execute('DELETE FROM difficulty_outcomes')
    state = {**state, 'last_intent': 'hint', 'hint_level': 1}
    assert record(previous, state)['outcome'] == 'hinted'
    with db.connection() as c:c.execute('DELETE FROM difficulty_outcomes')
    revised={**state,'last_intent':'discuss','revised_this_turn':True,'hint_level':0,'observations':[]}
    assert record(previous,revised)['outcome']=='unverified'


def test_personal_progress_and_recommendation_history_do_not_cross_users(client):
    source = question(client)
    for _ in range(3):outcome(question(client), 'independent')
    assert d.progression(source, k.get(source), update=True)['level'] == 4
    guest = client.post('/api/users', json={'name': '独立进度'}).json()['id']
    token = current_user.set(guest)
    try:
        assert d.progression(source, k.get(source), update=True)['level'] == 3
        with db.connection() as c:
            assert c.execute('SELECT count(*) FROM difficulty_outcomes').fetchone()[0] == 0
            assert c.execute('SELECT count(*) FROM difficulty_recommendations').fetchone()[0] == 0
    finally:current_user.reset(token)
