"""Fill missing 2026 answers with checked mathematical results; preserve all learner records.

The public reference PDFs are NOT the publisher's official grading rules. Two observed
paper-version conflicts remain explicit review cases, rather than silently changing a key.
"""
import copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import db,grading
from backend.ai import knowledge as k,vectors as v,cache

OFFICIAL_CATALOG='https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=6aa1910be119ac97297a608f'
SOURCE='2026 公开参考答案及数学核验；非官方评分细则'
MATRIX=r'\begin{pmatrix}1&-8&-9&9\\0&-1&-1&1\\-1&9&10&-10\\-1&7&8&-8\end{pmatrix}'
H=r'\begin{pmatrix}1&0&-1&1\\0&1&1&-1\end{pmatrix}'
LINEAR=r'$r(A)=2$，$\alpha_1,\alpha_2$ 为极大线性无关组；$\alpha_3=\alpha_2-\alpha_1$，$\alpha_4=\alpha_1-\alpha_2$。'+ '\n'+r'$H='+H+r'$，$A^{10}='+MATRIX+'$。'
ANSWERS={
 'math1':dict(enumerate(list('ADCCBABCAD'),1))|{
 11:'$1+z$',12:r'$\frac12$',13:r'$-\frac{\sqrt2}{8}$',14:r'$2\ln2$',15:'$a<0$',16:'$4$',
 17:r'在 $(-2,0)$ 处取得极大值 $8e^{-2}$；没有极小值。',
 18:r'按本地题图的 $f^{\prime\prime}(1)=0$ 条件：$f(u)=-e^{u-1}+e^{1-u}+u$。'+'\n'+r'若采用公开简答版对应的 $f^{\prime\prime\prime}(1)=0$ 条件，则 $f(u)=e^{u-1}+e^{1-u}-u$。两种条件不等价，须核对原出版物。',
 19:r'$I=\sqrt3\pi-\frac14$。',
 20:r'（1）$a>0$；（2）存在 $\xi\in(-1,1)$ 使 $F^{\prime\prime}(\xi)=0$。',
 21:LINEAR,
 22:r'（1）$f_T(t)=\frac n\theta e^{-nt/\theta}$（$t>0$），否则为 $0$；$a=n$，$D(\hat\theta)=\theta^2$。'+'\n'+r'（2）$\hat\theta=\frac{\sum_{i=1}^k t_i+(n-k)t_k}{k}$。'},
 'math2':dict(enumerate(list('ABADCBDBAD'),1))|{
 7:r'本地题图的区域为 $0\le x\le y\le1$，对应 B；公开完整卷与简答版的版本对应 D。两者区域/系数存在差异，须核对原出版物后再判分。',
 11:'$0<p<2$',12:r'$\frac12$',13:'$4$',14:r'$-2\pi$',15:r'$3\ln2-1$',16:'$2$',
 17:r'$I=4\sin\sqrt2-2\sqrt2$。',
 18:r'$f^{\prime}(x)=\frac{3x^3g(x^3)-\int_0^{x^3}g(u)\,du}{x^2}$（$x\ne0$），$f^{\prime}(0)=0$；在 $x=0$ 处连续。',
 19:r'在 $(-2,0)$ 处取得极大值 $8e^{-2}$；没有极小值。',
 20:r'$V=\frac{\pi^2}{6}-\frac{\sqrt3\pi}{16}$。',
 21:r'$y=-\frac12x^2-2x-4\ln(x-2)+11$（$x>2$）。',
 22:LINEAR}}
KEYS={'math1':{11:'1+z',12:'1/2',13:'-sqrt(2)/8',14:'2*log(2)',15:'a<0',16:'4'},
      'math2':{11:'0<p<2',12:'1/2',13:'4',14:'-2*pi',15:'3*log(2)-1',16:'2'}}
REVIEW={('math1',18):'本地题图为二阶导数条件，公开简答版结果对应三阶导数条件；需核对官方原文。',
        ('math2',7):'本地题图与公开答案版本的积分区域/系数不一致；需核对官方原文。'}
NOTES={('math1',17):r'解驻点条件并检查 Hessian，$(-2,0)$ 为极大点。',
 ('math1',18):r'比较混合偏导得 $(f^{\prime\prime}/u-f/u)^{\prime}=0$；按题图条件解 $f^{\prime\prime}-f=-u$，并代回初值核验。',
 ('math1',19):'补上相应闭合线段，应用格林公式后扣除补线的积分；注意曲线方向。',
 ('math1',20):r'严格递增给出两半区间积分的严格大小关系，从总积分为零得到 $a>0$。$F(-1)=F(0)=F(1)=0$，连续使用罗尔定理。',
 ('math1',21):'先由第三、四列对前两列的关系求 H，再用矩阵乘法或分解验证 A 的十次幂。',
 ('math1',22):'先求最小寿命的生存函数，再计算均值、方差；极大似然估计对对数似然求导并核对最大值。',
 ('math2',17):r'转换到极坐标：$\pi/4\le\theta\le3\pi/4$，$0\le r\le\sqrt2$；角度积分和径向积分分别计算。',
 ('math2',18):r'对非零 x 换元得到 $f(x)=x^{-1}\int_0^{x^3}g(u)du$；零点直接使用导数定义与 g 的连续性。',
 ('math2',19):r'解驻点条件并检查 Hessian，$(-2,0)$ 为极大点。',
 ('math2',20):r'拐点为 $(1/\sqrt3,3/4)$；分段积分 $\pi[\int_0^{1/\sqrt3}(3\sqrt3 x/4)^2dx+\int_{1/\sqrt3}^{\infty}(1+x^2)^{-2}dx]$。',
 ('math2',21):r'令 $v=y^{\prime}/x$ 化为 $xv^{\prime}=v^2+v$，用 $1/v$ 线性化；积分后代回两个初值。',
 ('math2',22):'先由第三、四列对前两列的关系求 H，再用矩阵乘法或分解验证 A 的十次幂。'}

def install():
    report={'installed':0,'preserved_existing':0,'needs_source_review':[],'new_model_calls':0,'official_catalog':OFFICIAL_CATALOG}
    for subject,values in ANSWERS.items():
        for n,answer in values.items():
            qid=f'real-{subject}-2026-q{n:02}'
            with db.connection() as c:old=k.bank_question(c,qid)
            if old['reference_answer'].strip():report['preserved_existing']+=1;continue
            analysis=k.get(old);oldfp=k.fingerprint(old);issue=REVIEW.get((subject,n),'')
            spec=copy.deepcopy(old['spec']);spec.update(answer_key='' if issue else (answer if n<=10 else KEYS.get(subject,{}).get(n,answer)),
                solution=answer,source=SOURCE,verified=False,reference_pdf=f'real-{subject}-2026/reference-answer.pdf',
                official_catalog=OFFICIAL_CATALOG,reference_issue=issue)
            with db.connection() as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('SELECT reference_answer FROM questions WHERE id=?',(qid,)).fetchone()[0]!=old['reference_answer']:raise ValueError('答案已在其他窗口更新，未覆盖')
                c.execute('UPDATE questions SET reference_answer=? WHERE id=?',(answer,qid))
                c.execute('INSERT OR REPLACE INTO question_grading VALUES(?,?)',(qid,grading.dumps(spec)))
                current=k.bank_question(c,qid)
                if analysis:
                    payload={key:value for key,value in analysis.items() if key in k.Analysis.model_fields}
                    payload['private_solution']=answer+'\n'+NOTES.get((subject,n),'按原题条件核对结果。')
                    payload['solution_basis']='reference';payload['reference_source']=SOURCE+'；'+OFFICIAL_CATALOG+'（仅书目，答案正文尚待核对）'
                    payload['rubric']='根据原题满分及实际作答对照参考结果。未取得官方评分细则时仅为参考估分。'
                    if issue:payload['uncertain']=True;payload['warnings']=(payload.get('warnings',[])[:7]+[issue])
                    c.execute('INSERT OR REPLACE INTO question_knowledge VALUES(?,?,?,?,?,?,?)',(qid,k.fingerprint(current),k.VERSION,k.Analysis.model_validate(payload).model_dump_json(),SOURCE,analysis['model_id'],k.now()))
                    document=v.document(current,payload)
                    c.execute('UPDATE question_embeddings SET fingerprint=? WHERE question_id=? AND fingerprint=? AND document_hash=?',
                              (k.fingerprint(current),qid,oldfp,cache.key(document['text'])))
            report['installed']+=1
            if issue:report['needs_source_review'].append({'question_id':qid,'reason':issue})
    return report

if __name__=='__main__':print(json.dumps(install(),ensure_ascii=False,indent=2),flush=True)
