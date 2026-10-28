"""Assemble the reusable tool, verified program/data packages and answer lists for server maintenance."""
import csv,json,shutil,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'packaging/windows'))
import library_update as lib
OUT=ROOT/'artifacts/408-workbooks'

def main():
 plan=json.loads((OUT/'import-plan-answers.json').read_text(encoding='utf-8'));stats=json.loads((OUT/'answer-report.json').read_text(encoding='utf-8'))
 if stats['not_generated'] or stats['questions']!=len(plan['questions']):raise ValueError('题目或答案统计尚未完成。')
 checks=[json.loads(l) for l in (ROOT/'artifacts/408-final-data-maintenance-check.log').read_text(encoding='utf-8',errors='replace').splitlines() if l.startswith('{')]
 if not checks or not checks[-1].get('frozen_data_import') or checks[-1].get('questions')!=len(plan['questions']):raise ValueError('完整数据包尚未通过原生 Windows 验收。')
 program=ROOT/'artifacts/master-release-2026.10.16-073317-1a3a7ec0.zip';data=ROOT/'artifacts/master-408-data.zip'
 with zipfile.ZipFile(data) as z:
  m=lib.read_manifest(z)
  if m['questions']!=stats['questions']:raise ValueError('交付数据包不是本次完整题库。')
 delivery=ROOT/'artifacts/master-maintenance-kit';delivery.mkdir(exist_ok=True)
 for source,name in [(ROOT/'artifacts/master-maintenance.exe','master-maintenance.exe'),(program,'master-program-update.zip'),(data,'master-408-data.zip'),(OUT/'needs-review.csv','needs-review.csv'),(OUT/'answer-report.json','answer-report.json')]:shutil.copy2(source,delivery/name)
 titles={p['id']:p['title'] for p in plan['papers']}
 with (delivery/'answers.csv').open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.writer(f);writer.writerow(['做题本','入库题号','原书题号','PDF页码','参考选项','状态'])
  for q in plan['questions']:
   spec=q['spec'];writer.writerow([titles[q['paper_id']],q['number'],spec['source_number'],spec['source_locations'][0]['page'],spec['answer_key'],'待复核' if spec.get('answer_uncertain') else 'AI参考答案，待核对'])
 (delivery/'README.txt').write_text(f'''master maintenance / Windows x64

本次包含 {stats['papers']} 份 408 做题本，共 {stats['questions']} 题。
已有明确参考选项：{stats['answered']} 题；待复核：{stats['needs_review']} 题。
答案由 AI 生成并做选项一致性检查，仍需对照原题核对，不是原书标准答案。
待复核题保留原图和生成说明，不自动判分。

服务器升级步骤：
1. 解压本包，双击 master-maintenance.exe。
2. 选择服务器上现有 master.exe 所在的目录。
3. 选择 master-program-update.zip，点击开始更新，等待成功。
4. 再选择 master-408-data.zip，点击开始更新，等待成功。
5. 浏览器按 Ctrl+F5 刷新，进入 408 题库选择对应做题本。

无需重新安装客户端，也无需在服务器安装 Python 或 Node.js。
不要把新的整个 data 目录覆盖到服务器。本工具增量入库，保留用户、
做题记录、草稿、标注及 API 设置；重复导入跳过已有内容，保留用户修改。
对题干和图片未改动且答案仍为空的题，会补齐空答案。

工具在维护前自动备份，备份位于现有 master 目录的 .updates 子目录。
备份包含私人配置，请妥善保管。维护会短暂停止服务，成功后自动启动并检查。
本包已在隔离 Windows 副本验收；远端服务器还需要按以上步骤实际执行。

answers.csv 是选择题答案列表；needs-review.csv 是待复核题清单。
下次继续使用同一个 master-maintenance.exe，选择新提供的题库 ZIP 即可。
开发机生成数据包：
python scripts/build_library_package.py --plan import-plan.json --uploads data/uploads --output master-new-data.zip
详细生成格式见项目 docs/题库维护与数据包.md。
''',encoding='utf-8-sig')
 (delivery/'verification.json').write_text(json.dumps({'windows_acceptance':checks[-1],'questions':stats['questions'],'automatic_reference_matches':len(json.loads((OUT/'consistency-report.json').read_text(encoding='utf-8'))['reference_matches']),'all_answers_manually_verified':False},ensure_ascii=False,indent=2),encoding='utf-8')
 files=sorted(p for p in delivery.iterdir() if p.is_file() and p.name!='checksums.sha256')
 (delivery/'checksums.sha256').write_text(''.join(lib.digest(p)+'  '+p.name+'\n' for p in files),encoding='ascii')
 output=ROOT/'artifacts/master-maintenance-kit.zip'
 with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as z:
  for path in sorted(delivery.iterdir()):
   if path.is_file():z.write(path,'master-maintenance-kit/'+path.name)
 with zipfile.ZipFile(output) as z:assert z.testzip() is None
 output.with_suffix('.zip.sha256').write_text(lib.digest(output)+'  '+output.name+'\n',encoding='ascii')
 print(json.dumps({'path':str(output),'bytes':output.stat().st_size,'sha256':lib.digest(output),'questions':stats['questions'],'answered':stats['answered'],'needs_review':stats['needs_review']},ensure_ascii=False))
if __name__=='__main__':main()
