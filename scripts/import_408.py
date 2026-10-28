"""Fetch public transcriptions of national 408 papers, preserve provenance, import idempotently.
No answer is included in question screenshots. Rendering is a separate local step.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import db,grading
from lxml import html,etree
import httpx

SOURCE='https://zhenti.beokayy.club'
CSS='''body{font:18px/1.8 "Microsoft YaHei",Arial,sans-serif;color:#111;background:white;margin:32px}article{margin:0 auto 28px;max-width:960px;border-bottom:1px solid #ddd;padding-bottom:24px}h2{font-size:22px}p{margin:10px 0}img,svg{max-width:100%;height:auto}figure{margin:16px 0}pre{white-space:pre-wrap;font:15px/1.6 Consolas,monospace;border:1px solid #ddd;padding:12px}table{border-collapse:collapse;width:100%;margin:15px 0}td,th{border:1px solid #999;padding:6px;text-align:left}.options{display:grid;grid-template-columns:1fr;gap:10px}.option{padding:2px 12px}article{break-inside:avoid}@media print{body{font-size:12px;line-height:1.6;margin:0}article{max-width:none}pre{font-size:10px}}'''

def text(node):
    if node.tag=='img':return '[题图：'+(node.get('alt') or '见配图')+']'
    if node.tag in ('script','style'):return ''
    value=node.text or ''
    for child in node:value+=text(child)+(child.tail or '')
    if node.tag=='sub':value='_{'+value+'}'
    elif node.tag=='sup':value='^{'+value+'}'
    if 'markdown-math' in (node.get('class') or ''):value='$'+value+'$'
    if node.tag in ('p','pre','li','tr','div','figure'):value+='\n'
    elif node.tag in ('td','th'):value+=' | '
    return value

def safe_node(node,folder,client):
    node=copy.deepcopy(node)
    for x in list(node.iter()):
        if x.tag in ('script','iframe','object','embed','style'):
            x.getparent().remove(x);continue
        for attr in list(x.attrib):
            if attr.startswith('on') or attr in ('srcset','loading','decoding','data-nimg','sizes','style'):del x.attrib[attr]
        if x.tag=='img':
            url=urljoin(SOURCE,x.get('src',''))
            if urlsplit(url).hostname!=urlsplit(SOURCE).hostname:raise ValueError('Unexpected external question image')
            name=Path(urlsplit(url).path).name
            asset=folder/name
            if not asset.exists():
                r=client.get(url);r.raise_for_status();content=r.content
                if name.endswith('.svg'):
                    svg=etree.fromstring(content,etree.XMLParser(resolve_entities=False,no_network=True))
                    for bad in svg.xpath('//*[local-name()="script" or local-name()="foreignObject"]'):bad.getparent().remove(bad)
                    for part in svg.iter():
                        for a in list(part.attrib):
                            if a.startswith('on') or a.endswith('href'):del part.attrib[a]
                    content=etree.tostring(svg)
                asset.write_bytes(content)
            x.set('src',name)
        if x.tag=='a':x.attrib.clear()
    return node

def prepare(cache:Path):
    uploads=db.DATA/'uploads';sources=db.DATA/'sources'/'408';sources.mkdir(parents=True,exist_ok=True)
    papers=[]
    with httpx.Client(timeout=45,follow_redirects=True) as client:
        for year in range(2009,2027):
            raw=cache/f'bok-{year}.html'
            if not raw.exists():
                r=client.get(f'{SOURCE}/paper/{year}');r.raise_for_status();raw.parent.mkdir(parents=True,exist_ok=True);raw.write_text(r.text,encoding='utf-8')
            parsed=html.parse(str(raw));cards=parsed.xpath('//article[contains(@class,"question-card")]')
            if len(cards)!=47:raise ValueError(f'{year}: expected 47 questions')
            folder=uploads/f'real-408-{year}';folder.mkdir(parents=True,exist_ok=True)
            qs=[];render=[]
            for n,card in enumerate(cards,1):
                assert card.get('id')==f'{year}-{n:02}'
                points=float(card.xpath('.//div[@class="question-meta"]/span')[1].text_content().split()[0])
                body=card.xpath('.//div[@class="question-body"]')[0]
                raw_answer=card.xpath('.//div[@class="answer-content"]')[0]
                solution=text(raw_answer).strip()
                # Some MCQ pages have a simple answer only; detailed analysis is supplemental.
                choices=card.xpath('.//button[contains(@class,"choice-option")]')
                stem=text(body).strip();kind='mcq' if n<=40 else 'subjective'
                if n<=40:
                    if len(choices)!=4:raise ValueError(f'{year}-{n}: incomplete options')
                    options=[]
                    for option in choices:
                        letter=option.xpath('.//span[@class="choice-letter"]')[0].text_content()
                        value=text(option.xpath('.//span[@class="choice-text"]')[0]).strip()
                        options.append(letter+'. '+value)
                    stem+='\n\n'+'\n'.join(options)
                    m=re.search(r'答案\s*[：:]\s*([ABCD])',solution)
                    if not m:raise ValueError(f'{year}-{n}: missing answer key')
                    key=m.group(1)
                else:key=solution
                header=f'{year} 年 408 统考真题 · {"选择题" if n<=40 else "综合应用题"} · {points:g}分\n'
                qid=f'real-408-{year}-q{n:02}'
                image_names=[]
                sanitized=safe_node(body,folder,client)
                markup=html.tostring(sanitized,encoding='unicode')
                if choices:
                    markup+='<div class="options">'
                    for option in choices:
                        letter=option.xpath('.//span[@class="choice-letter"]')[0].text_content()
                        c=safe_node(option.xpath('.//span[@class="choice-text"]')[0],folder,client)
                        markup+='<div class="option">'+letter+'. '+html.tostring(c,encoding='unicode')+'</div>'
                    markup+='</div>'
                if sanitized.xpath('.//img') or any(o.xpath('.//img') for o in choices):image_names=[f'real-408-{year}/Q{n:02}.png']
                spec={'kind':kind,'max_points':points,'answer_key':key,'solution':solution,'source':f'四〇八档案室公开整理；{SOURCE}/paper/{year}','verified':False,'points_known':True,'year':year}
                qs.append({'id':qid,'number':str(n),'text':header+stem,'images':image_names,'reference_answer':solution,'subject':'408','confirmed':False,'spec':spec})
                render.append(f'<article id="q{n:02}"><h2>{year} 年 408 · 第 {n} 题 · {points:g}分</h2>'+markup+'</article>')
            if sum(q['spec']['max_points'] for q in qs)!=150:raise ValueError(f'{year}: score sum is not 150')
            compiled='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>'+CSS+'</style><body>'+''.join(render)+'</body></html>'
            (folder/'paper.html').write_text(compiled,encoding='utf-8')
            snapshot=sources/f'{year}.html';snapshot.write_bytes(raw.read_bytes())
            source={'url':f'{SOURCE}/paper/{year}','fetched_at':grading.now(),'sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'questions':47,'max_points':150,'edition':'公开整理的统考真题；非教育部发布的原卷与官方评分细则','diagram_questions':[q['number'] for q in qs if q['images']]}
            (sources/f'{year}.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
            papers.append({'id':f'real-408-{year}','title':f'{year} 年 408 统考真题','subject':'408','filename':f'real-408-{year}/paper.pdf','questions':qs,'warnings':['公开整理版；题图与公式请对照核对。参考答案与解析并非官方评分细则。',source['url']]})
            print(f'{year}: 47 questions, 150 points, {len(source["diagram_questions"])} diagram questions',flush=True)
    path=cache/'408-import.json';path.write_text(json.dumps(papers,ensure_ascii=False),encoding='utf-8');return path

def install(path:Path):
    papers=json.loads(path.read_text(encoding='utf-8'));db.init_db();grading.init(recover_interrupted=False)
    with db.connection() as c:
        for p in papers:
            folder=db.DATA/'uploads'/p['id']
            if not (folder/'paper.pdf').exists():raise ValueError('Render paper PDFs first')
            for q in p['questions']:
                if any(not (db.DATA/'uploads'/f).exists() for f in q['images']):raise ValueError('Render question diagrams first')
            exists=c.execute('SELECT count(*) FROM questions WHERE paper_id=?',(p['id'],)).fetchone()[0]
            if exists:
                if exists!=47:raise ValueError(f'{p["id"]}: existing incomplete paper; refusing to overwrite')
                print(p['id'],'already imported; unchanged');continue
            stamp=grading.now()
            c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?)',(p['id'],p['title'],p['subject'],p['filename'],stamp,grading.dumps(p['warnings'])))
            for q in p['questions']:
                c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?)',(q['id'],p['id'],q['number'],q['text'],grading.dumps(q['images']),q['reference_answer'],'408',0,stamp))
                c.execute('INSERT INTO question_grading VALUES(?,?)',(q['id'],grading.dumps(q['spec'])))
    print(f'Imported {len(papers)} complete papers')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','install']);parser.add_argument('--cache',type=Path,default=ROOT/'artifacts/grading-acceptance');args=parser.parse_args()
    if args.mode=='prepare':print(prepare(args.cache))
    else:install(args.cache/'408-import.json')
