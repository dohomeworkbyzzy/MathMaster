import io
import json
import sqlite3
import threading
import time
import zipfile
import pytest
import pymupdf
from fastapi.testclient import TestClient
from backend import db
from backend.app import app
from backend.ai import adaptive,service
from backend.ai.adaptive import Reply
from backend.ai.provider import ProviderError

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    def prepare(q,cancelled):
        return {**q,'prepared':True,'kind':'limit','skills':['math2.limit.expansion_order'],
                'config':{'original_expression':'(exp(x)-1-x)/(1-cos(x))','point':'0','variable':'x','direction':'both'}}
    monkeypatch.setattr(service,'prepare',prepare)
    with TestClient(app) as c:yield c

def create(c,text='求 x→0 时 (exp(x)-1-x)/(1-cos(x)) 的极限',confirmed=True,subject='数学二'):
    response=c.post('/api/questions',json={'number':'1','text':text,'subject':subject,'confirmed':confirmed})
    assert response.status_code==200,response.text
    return response.json()['id']

def finished(c,sid):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        state=c.get('/api/ai/sessions/'+sid).json()
        if not state['busy']:return state
        time.sleep(.05)
    pytest.fail('AI turn did not finish')

def send(c,state,text,rid):
    response=c.post('/api/ai/sessions/'+state['id']+'/turns',json={'text':text,'request_id':rid,'version':state['version']})
    assert response.status_code==202,response.text
    state=finished(c,state['id'])
    assert state['turns'][-1]['status']=='complete',state['turns'][-1]
    return state

def replies(monkeypatch,items):
    sequence=iter(items)
    monkeypatch.setattr(adaptive,'model_reply',lambda *a,**k:(Reply.model_validate(next(sequence)),{'model_id':'fixture','usage':{}}))

def test_original_question_two_methods_actual_tools_history_notes_and_backup(client,monkeypatch,tmp_path):
    qid=create(client);other=create(client,'另外一题')
    state=client.post(f'/api/questions/{qid}/ai',json={}).json()
    assert state['question_id']==qid
    assert client.post(f'/api/questions/{qid}/ai',json={}).json()['id']==state['id']
    replies(monkeypatch,[
        {'intent':'method','method':'泰勒展开','message':'先确定要保留的阶数。','next_question':'你要展开哪两部分，到几阶？'},
        {'intent':'calculate','tool_calls':[{'tool':'math.series','input':{'expression':'exp(x)-1-x','through_degree':2}},{'tool':'math.series','input':{'expression':'1-cos(x)','through_degree':2}}]},
        {'intent':'calculate','message':'分子分母都出现二阶主导项。','next_question':'比值趋于多少？'},
        {'intent':'answer','action':'complete','final_answer':'1','method':'泰勒展开','message':'结果为1。','next_question':'另一种方法是洛必达，第一步先确认什么形式？'},
        {'intent':'calculate','method':'洛必达','tool_calls':[{'tool':'math.lhopital_step','input':{'numerator':'exp(x)-1-x','denominator':'1-cos(x)','condition_note':'0/0型，附近分母导数非零'}}]},
        {'intent':'calculate','method':'洛必达','message':'分别求导得 exp(x)-1 和 sin(x)。','next_question':'现在是哪一种未定式？'},
        {'intent':'answer','action':'complete','final_answer':'1','method':'洛必达','message':'第二种解法完成。'}])
    state=send(client,state,'我想用泰勒展开','a')
    assert state['state']['cards']==[]
    state=send(client,state,'帮我把分子分母都展开到二阶','b')
    cards=state['state']['cards'];assert len(cards)==2
    assert cards[0]['result']['remainder']=='O(x**3)'
    assert cards[1]['result']['polynomial']=='x**2/2'
    duplicate=client.post('/api/ai/sessions/'+state['id']+'/turns',json={'text':'帮我把分子分母都展开到二阶','request_id':'b','version':0})
    assert duplicate.status_code==202
    assert len(duplicate.json()['turns'])==2
    hist=client.get('/api/math/history',params={'question_id':qid}).json();assert len(hist)==2
    assert client.get('/api/math/history',params={'question_id':other}).json()==[]
    hid=cards[0]['history_id']
    assert client.post(f'/api/questions/{qid}/calculations/{hid}',json={}).status_code==200
    assert len(client.get(f'/api/questions/{qid}').json()['calculations'])==1
    state=send(client,state,'我认为比值趋于1','c')
    assert state['state']['completed_methods']==['泰勒展开']
    assert state['state']['completion_check']=='valid'
    assert state['state']['stage']=='alternative'
    assert state['state']['final_answer']=='1'
    records=client.get('/api/grading/questions/'+qid).json()['history']
    assert records[0]['source']=='ai' and records[0]['answer']=='1'
    assert '泰勒展开' in records[0]['reasoning']
    assert '系统代算' in records[0]['reasoning'] and r'O\left' in records[0]['reasoning']
    state=send(client,state,'我用洛必达，是0/0型，附近分母导数非零，先帮我分别求导','d')
    assert state['state']['cards'][-1]['result']['numerator']=='exp(x) - 1'
    state=send(client,state,'由主导项比值可知极限为1','e')
    assert state['state']['completed_methods']==['泰勒展开','洛必达']
    assert state['state']['stage']=='completed'
    assert client.get('/api/stats').json()['questions']==2
    archive=zipfile.ZipFile(io.BytesIO(client.get('/api/backup').content))
    (tmp_path/'backup.db').write_bytes(archive.read('mathmaster.db'))
    with sqlite3.connect(tmp_path/'backup.db') as con:
        assert con.execute('SELECT count(*) FROM ai_turns').fetchone()[0]==5
        assert con.execute('SELECT count(*) FROM questions').fetchone()[0]==2

def test_scan_is_the_same_bank_and_408_is_supported(client):
    document=pymupdf.open();page=document.new_page();page.insert_text((50,90),'1. Find the limit of sin(x)/x.');data=document.tobytes();document.close()
    response=client.post('/api/papers/import',data={'subject':'数学二','title':'扫描接入测试'},files={'file':('exam.pdf',data,'application/pdf')})
    assert response.status_code==200,response.text
    q=client.get('/api/questions',params={'paper_id':response.json()['id']}).json()[0]
    assert q['images'] and not q['confirmed']
    state=client.post('/api/questions/'+q['id']+'/ai',json={}).json()
    assert state['question_id']==q['id']
    with db.connection() as con:
        snap=json.loads(con.execute('SELECT snapshot FROM ai_sessions WHERE id=?',(state['id'],)).fetchone()['snapshot'])
    assert snap['images']==q['images']
    assert client.get('/api/files/'+q['images'][0]).status_code==200
    assert create(client,'Cache地址划分',subject='408')

def test_edit_invalidates_the_ai_session(client):
    qid=create(client);old=client.post(f'/api/questions/{qid}/ai',json={}).json()
    assert client.put(f'/api/questions/{qid}',json={'number':'1','text':'修改过的原题','subject':'数学二','confirmed':True}).status_code==200
    assert client.get('/api/ai/sessions/'+old['id']).json()['stale']
    response=client.post('/api/ai/sessions/'+old['id']+'/turns',json={'text':'继续','version':0,'request_id':'a'})
    assert response.status_code==409
    assert client.post(f'/api/questions/{qid}/ai',json={}).json()['id']!=old['id']

def test_cancel_does_not_commit_computation(client,monkeypatch):
    started=threading.Event()
    def waiting(context,cancelled=None):
        started.set()
        deadline=time.monotonic()+10
        while not cancelled() and time.monotonic()<deadline:time.sleep(.02)
        raise ProviderError('本轮已取消')
    monkeypatch.setattr(adaptive,'model_reply',waiting)
    qid=create(client);state=client.post(f'/api/questions/{qid}/ai',json={}).json()
    response=client.post('/api/ai/sessions/'+state['id']+'/turns',json={'text':'帮我算当前步骤','version':0,'request_id':'a'})
    assert response.status_code==202 and started.wait(3)
    assert client.post('/api/ai/sessions/'+state['id']+'/cancel',json={}).json()['requested']
    state=finished(client,state['id'])
    assert state['turns'][0]['status']=='cancelled'
    assert state['turns'][0]['user_text']=='帮我算当前步骤'
    assert state['state']['cards']==[]
    assert client.get('/api/math/history',params={'question_id':qid}).json()==[]

def test_live_progress_duplicate_receipt_and_visible_failure(client,monkeypatch):
    started=threading.Event();release=threading.Event();calls=[]
    def model(*a,**kw):
        calls.append(1);started.set();assert release.wait(5)
        raise ProviderError('模型请求超时，输入已保留，可重试。')
    monkeypatch.setattr(adaptive,'model_reply',model)
    state=client.post('/api/questions/'+create(client)+'/ai',json={}).json();sid=state['id']
    payload={'text':'我准备用泰勒展开','version':0,'request_id':'receipt'}
    response=client.post('/api/ai/sessions/'+sid+'/turns',json=payload)
    assert response.status_code==202 and started.wait(3)
    live=client.get('/api/ai/sessions/'+sid).json()
    assert live['turns'][0]['progress']['phase']=='model'
    assert live['turns'][0]['elapsed_seconds']>=0
    again=client.post('/api/ai/sessions/'+sid+'/turns',json=payload).json()
    assert len(again['turns'])==1 and len(calls)==1
    assert client.post('/api/ai/sessions/'+sid+'/turns',json={**payload,'text':'其他内容'}).status_code==409
    release.set();done=finished(client,sid)
    assert done['turns'][0]['status']=='failed' and done['turns'][0]['progress']['phase']=='failed'
    assert '模型请求超时' in done['turns'][0]['error']
    assert client.post('/api/ai/sessions/'+sid+'/turns',json=payload).json()['turns']==done['turns']
    assert len(calls)==1

def test_tool_failure_shows_specific_reason_instead_of_empty_success(client,monkeypatch):
    replies(monkeypatch,[
        {'intent':'calculate','tool_calls':[{'tool':'math.solve','input':{'equations':['x=1'],'variables':['unsupported']}}]},
        {'intent':'calculate','message':'继续整理'},
        {'intent':'calculate','message':'继续整理'}])
    state=client.post('/api/questions/'+create(client)+'/ai',json={}).json()
    client.post('/api/ai/sessions/'+state['id']+'/turns',json={'text':'帮我解这个方程','version':0,'request_id':'bad-tool'})
    done=finished(client,state['id']);turn=done['turns'][0]
    assert turn['status']=='failed' and 'math.solve' in turn['error'] and 'variables.0' in turn['error']
    assert not turn['message'] and done['state']['cards']==[]

def test_empty_model_reply_is_not_a_successful_turn():
    with pytest.raises(ValueError):Reply.model_validate({'message':'  ','next_question':''})
    assert not adaptive.calculation_requested('你帮我把这两个式子列成好看的形式进行对比一下我再计算')
    assert adaptive.calculation_requested('把这两个方程排版并帮我解出zx和zy')

def test_learning_needs_distinct_questions_and_accepts_correction(client,monkeypatch):
    replies(monkeypatch,[{'message':'检查抵消项','observations':[{'skill_id':'math2.limit.expansion_order','quote':'一阶就够','judgement':'incorrect','reason':'一阶项抵消'}]}]*2)
    for i in range(2):
        qid=create(client);state=client.post(f'/api/questions/{qid}/ai',json={}).json()
        send(client,state,'一阶就够',str(i))
        summary=client.get('/api/ai/learning').json()
        assert summary[0]['status']==('待观察' if i==0 else '需要巩固')
    assert client.post('/api/ai/observations/'+summary[0]['evidence'][0]['id']+'/exclude',json={}).status_code==200
    assert client.get('/api/ai/learning').json()[0]['status']=='待观察'

def test_reference_exposure_excludes_new_learning_evidence(client,monkeypatch):
    replies(monkeypatch,[{'message':'检查抵消项','observations':[{'skill_id':'math2.limit.expansion_order','quote':'一阶就够','judgement':'incorrect','reason':'一阶项抵消'}]}])
    qid=create(client);state=client.post(f'/api/questions/{qid}/ai',json={}).json()
    state=client.post('/api/ai/sessions/'+state['id']+'/answer-exposed',json={}).json()
    send(client,state,'一阶就够','a')
    assert client.get('/api/ai/learning').json()==[]

@pytest.mark.parametrize(('text','expected'),[
 ('帮我解这两个方程',True),('请解释为什么需要求导',False),
 ('我想用泰勒展开',False),('帮我把分子分母展开到二阶',True),
 ('请分析一下用哪个方法',False),('先不计算，只解释思路',False),
 ('为什么要消去一次项？然后帮我展开到二阶',True)])
def test_natural_requests_distinguish_explanation_and_delegated_calculation(text,expected):
    assert adaptive.calculation_requested(text)==expected


def test_variable_integral_derivative_check_finishes_instead_of_integrate_parse_failure(client,monkeypatch):
    from backend.ai import registry
    expression='integrate(phi(t)+phi(-t),(t,x-y,x+y))'
    wrong="phi'(x+y)-phi'(-x+y)+phi'(x-y)-phi'(y-x)"
    correct="phi'(x+y)-phi'(-x-y)+phi'(x-y)-phi'(y-x)"
    monkeypatch.setattr(service,'prepare',lambda q,cancelled:{**q,'prepared':True,'kind':'scratch','skills':['math2.derivative.chain'],'config':{}})
    qid=create(client,text=r'设 u(x,y)=从 x-y 到 x+y 对 phi(t)+phi(-t) 积分，phi 具有一阶导数，核对各二阶偏导。')
    state=client.post(f'/api/questions/{qid}/ai',json={}).json()
    replies(monkeypatch,[
        {'tool_calls':[{'tool':'math.check_derivative','input':{'expression':expression,'variables':['x','y'],'proposed':wrong},'label':'核对混合偏导'}]},
        {'message':'按你这里的一元函数记号核对，第二项应是负的 x+y；先停在这一步修正。'}])
    state=send(client,state,'请检查我的混合偏导，如果正确再帮我算其余二阶偏导：'+wrong,'integral-check-wrong')
    result=state['state']['cards'][-1]['result']
    assert result['verdict']=='not_equal' and result['counterexample']
    assert state['turns'][-1]['error']=='' and len(state['state']['cards'])==1
    replies(monkeypatch,[
        {'tool_calls':[{'tool':'math.check_derivative','input':{'expression':expression,'variables':['x','y'],'proposed':correct},'label':'再次核对混合偏导'},
                       {'tool':'math.differentiate','input':{'expression':expression,'variables':['x','x']},'label':'计算二阶 x 偏导'},
                       {'tool':'math.differentiate','input':{'expression':expression,'variables':['y','y']},'label':'计算二阶 y 偏导'}]},
        {'message':'当前混合偏导核验通过，其余两项已经列出，供你自行比对。'}])
    state=send(client,state,'请检查修正后的混合偏导，如果正确再帮我算其余二阶偏导：'+correct,'integral-check-correct')
    cards=state['state']['cards']
    assert len(cards)==4 and cards[1]['result']['verdict']=='symbolically_equal_on_common_domain'
    assert all(card['result']['verified'] for card in cards[1:])
    import sympy as sp
    from backend.parser import parse
    assert sp.simplify(parse(cards[2]['result']['exact_result'])-parse(cards[3]['result']['exact_result']))==0
