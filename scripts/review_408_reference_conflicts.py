"""Record explicit reasoning corrections for identical questions with conflicting generated answers."""
import json,shutil
from datetime import datetime,timezone
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'artifacts/408-workbooks'
corrections={
 'jc26-cn-q0284':('B','已知192.168.9.128/26覆盖128～191。若原网络为192.168.9.0/24，可分为0/25、128/26、192/26三个子网，因此A、C都可行。若原网络为192.168.9.128/25，可分为128/26、192/27、224/27，D也可行。若加入0/26，则在能包含它和已知子网的最小原网络/24内，余下64～127及192～255不连续，至少还需两个子网，共至少四个，故B不可能。',False),
 'jc26-co-q0181':('A','4M=2^22个存储单元需要22位逻辑地址。DRAM采用行、列地址复用，行地址和列地址分两次送入同一组引脚，不能把两次使用的引脚重复相加；11根地址引脚即可分别传送11位行地址和11位列地址。每片还有8根数据引脚，合计11+8=19根，选A。存储器总容量256MB不改变单片引脚数。',False),
 'jc26-co-q0250':('C','现有公开真题参考答案为C（3次）。该整理解析采用地址0～1、4～5、8～9映射第0组，2～3、6～7映射第1组的约定，按LRU模拟时第7、8、10次访问命中。需要注意：若严格按题面“按字编址、每块1字”并用块号mod2取组号，则所有给定地址均落入同一组，结果与此参考约定不同。本题保留公开参考选项C，并标记待核对映射约定，不据此自动判分。',True),
 'jc26-co-q0394':('A','题目限定中断服务程序内部。关中断和保存断点由进入服务程序前的中断响应过程完成，不能把这两项硬件响应操作再算作服务程序步骤。服务程序先保护现场I，再处理中断V、恢复现场VI，结束前开中断II，最后中断返回VII。因此顺序I→V→VI→II→VII，选A。单级中断不在中断事件处理期间开放嵌套。',False),
 'jc26-co-q0537':('A','关中断及保存断点属于进入服务程序之前的中断响应过程。题目问服务程序内部的顺序，应先保护现场I，再处理中断事件V、恢复现场VI，然后开中断II并执行中断返回VII。故为I→V→VI→II→VII，选A；把保存断点或关中断列入该服务程序内部序列，会混淆硬件响应与软件服务两个阶段。',False),
 'jc26-co-q0430':('B','单周期CPU的每条指令恰占一个时钟周期，所以CPI=1；多周期CPU每条指令需要多个周期。基本单发射流水线在理想稳态下每周期完成一条指令，CPI=1；超标量流水线理想情况下每周期可完成多条指令，CPI可小于1。因此满足题意的是I、III，选B。',False),
 'jc26-co-q0470':('C','100MHz总线的时钟周期为10ns。地址和数据线复用，传128位数据前先用一个周期传送地址；32位总线每个数据周期传32位，需128/32=4个数据周期。突发传送仅省去重复地址周期，仍需1+4=5个周期，共50ns，选C。',False),
 'jc26-os-q0122':('B','父、子进程分别拥有进程控制块和独立的虚拟地址空间；创建子进程时的写时复制不等于两者共享同一虚拟地址空间。因此B错误。它们可以并发执行，并必须互斥访问同一临界资源，A、C、D均不构成题目要求的错误叙述。',False),
 'jc26-os-q0337':('B','对合法虚拟页的访问产生缺页时，若有空闲页框可分配内存，若无空闲页框可能需要置换页面，所以II、III可能执行。地址越界应在地址合法性检查中处理，不能把越界错等同于题设的合法页缺页处理。故选B。',False),
}
report=json.loads((OUT/'consistency-report.json').read_text(encoding='utf-8'));matches={r['id']:r for r in report['reference_matches']};records=[]
for path in (OUT/'answers').glob('*-v3-*.json'):
 parts=path.stem.split('-');key=parts[2]+'-'+parts[3]+'-'+parts[-1]
 if key not in corrections:continue
 answer,explanation,uncertain=corrections[key];old=json.loads(path.read_text(encoding='utf-8'))
 revisions=OUT/'answer-revisions';revisions.mkdir(exist_ok=True)
 backup=revisions/(path.stem+'-before-reference-review.json')
 if not backup.exists():shutil.copyfile(path,backup)
 old.update(answer_key=answer,explanation=explanation,uncertain=uncertain,uncertainties=['公开参考与通常组号推导的映射约定不一致，待核对。'] if uncertain else [],reviewed_at=datetime.now(timezone.utc).isoformat(),review_method='same_question_reference_and_explicit_reasoning')
 if old['id'] in matches:old['reference_check']=matches[old['id']]
 path.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8');records.append({'id':old['id'],'answer':answer,'uncertain':uncertain})
(OUT/'reference-review.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print('Reasoning corrections recorded',len(records))
