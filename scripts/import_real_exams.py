"""Import publicly collected 2012–2026 Math I/II exams into the local library.

Original question images are authoritative. No OCR formula is marked confirmed.
Downloads use pinned repository commits and verify Git blob checksums. Rerunning
does not overwrite questions, answers, notes, or attempts already in the library.
"""
import concurrent.futures
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import db
import pymupdf
from PIL import Image

SOURCES = db.DATA / 'sources'
REPO = 'lx-ruc/kaoyanshuxue'
COMMIT = '196dc9d2d8271978a030a3721a828c8723cd3864'
PATTERN = re.compile(r'kaoyan_math_images/(数学[一二])/(201[2-9]|202[0-5])/Q(\d+)_id(\d+)\.png$')


def blob_hash(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def download(url, dest, expected=None):
    if dest.exists() and (not expected or blob_hash(dest.read_bytes()) == expected):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'MathMaster-local-study'})
            with urllib.request.urlopen(req, timeout=45) as response:
                content = response.read(30_000_001)
            if len(content) > 30_000_000:
                raise ValueError('Source file exceeds download limit')
            if expected and blob_hash(content) != expected:
                raise ValueError('Git blob checksum mismatch: ' + url)
            temporary = dest.with_suffix(dest.suffix + '.part')
            temporary.write_bytes(content)
            temporary.replace(dest)
            return
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def load_tree():
    path = SOURCES / 'kaoyanshuxue-tree.json'
    if not path.exists():
        download(f'https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1', path)
    tree = json.loads(path.read_text(encoding='utf-8'))
    if tree['sha'] != COMMIT or tree.get('truncated'):
        raise ValueError('Source tree must be complete and match the pinned commit')
    return tree


def paper_id(subject, year):
    return f'real-math{1 if subject == "数学一" else 2}-{year}'


def question_pdf(paths, destination):
    """A clearly labelled local compilation, not a claimed original exam PDF."""
    doc = pymupdf.open()
    for number, path in enumerate(paths, 1):
        with Image.open(path) as image:
            width, height = image.size
        page_height = max(200, height * 540 / width + 65)
        page = doc.new_page(width=595, height=page_height)
        page.insert_text((25, 22), f'Question {number} | compiled from source image', fontsize=9)
        page.insert_image(pymupdf.Rect(25, 40, 565, page_height - 25), filename=str(path))
    doc.set_metadata({'title': destination.parent.name, 'subject': 'Local compilation of publicly collected question images', 'author': REPO})
    doc.save(destination, deflate=True)
    doc.close()


def import_images(tree):
    entries = [(v, PATTERN.match(v['path'])) for v in tree['tree'] if PATTERN.match(v['path'])]
    if len(entries) != 634:
        raise ValueError(f'Expected 634 question images, found {len(entries)}')
    groups = {}
    jobs = []
    for entry, match in entries:
        subject, year, number, external_id = match.groups()
        pid = paper_id(subject, year)
        filename = f'{pid}/Q{int(number):02d}.png'
        destination = db.DATA / 'uploads' / filename
        url = f'https://raw.githubusercontent.com/{REPO}/{COMMIT}/' + urllib.parse.quote(entry['path'])
        groups.setdefault((subject, int(year)), []).append((int(number), filename, entry, url))
        jobs.append((url, destination, entry['sha']))
    def fetch(job):
        download(*job)
        with Image.open(job[1]) as image:
            image.verify()
        return job[1]
    print(f'Downloading/verifying {len(jobs)} question images (25 MB)…', flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for index, _ in enumerate(pool.map(fetch, jobs), 1):
            if index % 50 == 0 or index == len(jobs):
                print(f'Images ready: {index}/{len(jobs)}', flush=True)
    metadata = {}
    for index, subject in enumerate(('数学一', '数学二'), 1):
        path = SOURCES / f'math{index}-answers.json'
        source_path = f'kaoyan_math_images/{subject}/answers.json'
        expected = next(v['sha'] for v in tree['tree'] if v['path'] == source_path)
        download(f'https://raw.githubusercontent.com/{REPO}/{COMMIT}/' + urllib.parse.quote(source_path), path, expected)
        metadata.update(json.loads(path.read_text(encoding='utf-8')))
    manifest = []
    for (subject, year), rows in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        rows.sort()
        expected = 23 if year < 2021 else 22
        if [row[0] for row in rows] != list(range(1, expected + 1)):
            raise ValueError(f'{year} {subject}: question numbers incomplete')
        pid = paper_id(subject, year)
        dest = db.DATA / 'uploads' / pid
        pdf = dest / 'question-images.pdf'
        if not pdf.exists():
            question_pdf([db.DATA / 'uploads' / r[1] for r in rows], pdf)
        warnings = ['来源为公开真题整理，尚未逐题人工校对，请以题图为准。',
                    '此 PDF 是逐题原图的本地合订本，不是原始扫描试卷。题目公式未作 OCR 转录。',
                    f'来源：https://github.com/{REPO}；固定版本：{COMMIT}。']
        stamp = datetime.now(timezone.utc).isoformat()
        with db.connection() as conn:
            conn.execute('INSERT OR IGNORE INTO papers VALUES(?,?,?,?,?,?)',
                         (pid, f'{year}年考研{subject}真题', subject, f'{pid}/question-images.pdf', stamp, json.dumps(warnings, ensure_ascii=False)))
            for number, filename, entry, url in rows:
                info = metadata[f'{subject}_{year}_Q{number:02d}']
                if info['index'] != number or str(info['question_id']) != PATTERN.match(entry['path'])[4]:
                    raise ValueError('Question metadata mismatch')
                kind = {1: '选择题', 2: '填空题', 3: '解答题'}.get(info['type'], '题目')
                text = f'{year}年考研{subject} · 第{number}题 · {kind} · {info["score"]}分\n知识点：{info.get("knowledge_point", "")}\n请阅读下方原始题图，公式以图片为准。'
                reference = f'网络整理参考答案：{info["answer"]}。请自行核对。' if info.get('answer') else ''
                conn.execute('INSERT OR IGNORE INTO questions(id,paper_id,number,text,images,reference_answer,subject,confirmed,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                             (f'{pid}-q{number:02d}', pid, str(number), text, json.dumps([filename]), reference, subject, 0, stamp))
        record = {'paper_id': pid, 'year': year, 'subject': subject, 'count': expected, 'source': f'https://github.com/{REPO}', 'commit': COMMIT,
                  'pdf_kind': 'compiled_question_images', 'questions': [{'number': n, 'image': filename, 'source_url': url, 'git_blob_sha1': entry['sha'], 'sha256': hashlib.sha256((db.DATA / 'uploads' / filename).read_bytes()).hexdigest()} for n, filename, entry, url in rows]}
        (dest / 'provenance.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest.append(record)
        print(f'Imported {year} {subject}: {expected} questions', flush=True)
    return manifest


def import_2026():
    # Coordinates were checked against all eight question pages. The PDF cover
    # is excluded. Y coordinates refer to a 1.2x rendering, 1011 pixels tall;
    # include formula ascenders and retain questions crossing a page boundary.
    layouts = {
        1: {2: [(1,145),(2,300),(3,425),(4,613),(5,840)],
            3: [(6,150),(7,332),(8,556),(9,674),(10,817)],
            4: [(11,259),(12,291),(13,330),(14,386),(15,428),(16,542),(17,680),(18,738)],
            5: [(19,83),(20,178),(21,287),(22,515)]},
        2: {2: [(1,132),(2,280),(3,467),(4,617),(5,800)],
            3: [(6,213),(7,372),(8,562),(9,649),(10,784)],
            4: [(11,109),(12,164),(13,226),(14,259),(15,336),(16,370),(17,532),(18,606),(19,700),(20,775),(21,885)],
            5: [(22,140)]},
    }
    continuations = {1: [(5,3,86,145),(10,4,90,192)],
                     2: [(5,3,93,190),(21,5,86,125)]}
    treepath = SOURCES / 'mathonline-tree.json'
    commit = '88a784403ccf8acb8161b6c43142116b88a62b6f'
    if not treepath.exists():
        download(f'https://api.github.com/repos/fjw345/mathonline/git/trees/{commit}?recursive=1', treepath)
    tree = json.loads(treepath.read_text(encoding='utf-8'))
    if tree['sha'] != commit or tree.get('truncated'):
        raise ValueError('2026 source tree version mismatch')
    records = []
    for index, subject in enumerate(('数学一','数学二'), 1):
        label = '数一' if index == 1 else '数二'
        matches = [v for v in tree['tree'] if v['path'].startswith('resource/') and f'/2026考研数学真题及答案（{label}）/' in v['path'] and v['path'].endswith('真题.pdf')]
        if len(matches) != 1:
            raise ValueError('2026 original question PDF not unique')
        entry = matches[0]
        pid = paper_id(subject, 2026)
        folder = db.DATA / 'uploads' / pid
        url = f'https://raw.githubusercontent.com/fjw345/mathonline/{commit}/' + urllib.parse.quote(entry['path'])
        path = folder / 'original.pdf'
        download(url, path, entry['sha'])
        document = pymupdf.open(path)
        if len(document) != 5:
            raise ValueError('2026 source layout changed')
        images = {number: [] for number in range(1,23)}
        regions = {number: [] for number in range(1,23)}
        def crop(number, page_number, top, bottom, suffix=''):
            page = document[page_number-1]
            region = pymupdf.Rect(0, page.rect.height*top/1011, page.rect.width, page.rect.height*bottom/1011)
            filename = f'{pid}/Q{number:02d}{suffix}.png'
            page.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=region,alpha=False).save(db.DATA/'uploads'/filename)
            images[number].append(filename)
            regions[number].append({'page':page_number,'top':top/1011,'bottom':bottom/1011})
        for page_number, anchors in layouts[index].items():
            for position, (number, top) in enumerate(anchors):
                bottom = anchors[position+1][1] if position+1 < len(anchors) else (780 if index==1 else 380) if page_number==5 else 930
                crop(number,page_number,top,bottom)
        for number, page_number, top, bottom in continuations[index]:
            crop(number,page_number,top,bottom,'-continuation')
        document.close()
        warnings = ['来源为公开整理扫描卷，已检查题号与截图范围，未逐题校验题干和参考答案。',
                    '保留完整原始 PDF 和跨页续题截图；数学公式以原始题图为准，不采用 OCR 公式。',
                    f'来源：https://github.com/fjw345/mathonline；固定版本：{commit}。']
        stamp = datetime.now(timezone.utc).isoformat()
        with db.connection() as conn:
            conn.execute('INSERT OR IGNORE INTO papers VALUES(?,?,?,?,?,?)',
                         (pid,f'2026年考研{subject}真题',subject,f'{pid}/original.pdf',stamp,json.dumps(warnings,ensure_ascii=False)))
            for number in range(1,23):
                kind = '选择题' if number<=10 else '填空题' if number<=16 else '解答题'
                text = f'2026年考研{subject} · 第{number}题 · {kind}\n请阅读下方原始题图，公式以图片为准。'
                conn.execute('INSERT OR IGNORE INTO questions(id,paper_id,number,text,images,reference_answer,subject,confirmed,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                             (f'{pid}-q{number:02d}',pid,str(number),text,json.dumps(images[number]),'',subject,0,stamp))
        record = {'paper_id':pid,'year':2026,'subject':subject,'count':22,'source':'https://github.com/fjw345/mathonline','source_url':url,'commit':commit,'git_blob_sha1':entry['sha'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pdf_kind':'original_scanned_question_paper',
                  'questions':[{'number':n,'images':images[n],'regions':regions[n]} for n in range(1,23)]}
        (folder/'provenance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        records.append(record)
        print(f'Imported 2026 {subject}: 22 questions',flush=True)
    return records


def main():
    SOURCES.mkdir(parents=True, exist_ok=True)
    db.init_db()
    backup = SOURCES / 'before-real-exams.db'
    if not backup.exists():
        with db.connection() as source, sqlite3.connect(backup) as target:
            source.backup(target)
    manifest = import_images(load_tree())
    manifest.extend(import_2026())
    (SOURCES / 'real-exams-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
