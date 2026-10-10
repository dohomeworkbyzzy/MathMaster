"""Local exam extraction. Original PDF raster images remain the authority."""
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import pymupdf as fitz
from PIL import Image

QUESTION=re.compile(r'^\s*(?:第\s*)?(\d{1,2})\s*(?:[.．、)）]|题)\s*')
MAX_PAGES=80

def tesseract_binary():
    exe=os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    if not exe and os.name!='nt':
        portable=Path(__file__).resolve().parents[1]/'.tools/tesseract-wrapper'
        if portable.exists():exe=str(portable)
    if not exe and os.name=='nt':
        candidate=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Tesseract-OCR/tesseract.exe'
        if candidate.exists():exe=str(candidate)
    return exe

def ocr_lines(path):
    exe=tesseract_binary()
    if not exe:return [],'未安装本地 Tesseract：已保留扫描页截图，请人工拆题或安装后重新导入。'
    import pytesseract
    from pytesseract import Output
    pytesseract.pytesseract.tesseract_cmd=exe
    available=pytesseract.get_languages(config='')
    lang='+'.join(l for l in ('chi_sim','eng') if l in available)
    if not lang:return [],'Tesseract 没有中文或英文语言包，请人工检查截图。'
    with Image.open(path) as im:
        data=pytesseract.image_to_data(im,lang=lang,output_type=Output.DICT,timeout=25)
        groups={}
        for i,word in enumerate(data['text']):
            if not word.strip():continue
            k=(data['block_num'][i],data['par_num'][i],data['line_num'][i])
            g=groups.setdefault(k,{'text':[],'y':data['top'][i]})
            g['text'].append(word)
        return [{'text':' '.join(v['text']),'y':v['y']/im.height} for v in groups.values()],None

def pdf_extract(path,out_dir):
    questions=[]; warnings=[]; current=None
    doc=fitz.open(path)
    if doc.needs_pass:raise ValueError('暂不支持加密 PDF，请先解除密码。')
    if len(doc)>MAX_PAGES:raise ValueError(f'单次导入最多 {MAX_PAGES} 页。')
    for page_index,page in enumerate(doc):
        if page.rect.width>2000 or page.rect.height>3000:raise ValueError('PDF 页面尺寸过大。')
        image_name=f'page-{page_index+1}.png'; full_path=out_dir/image_name
        scale=min(1.8,2200/max(page.rect.width,page.rect.height))
        page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(full_path)
        lines=[]
        for block in page.get_text('dict',sort=True)['blocks']:
            if 'lines' not in block:continue
            for line in block['lines']:
                text=''.join(span['text'] for span in line['spans'])
                if text.strip():lines.append({'text':text,'y':line['bbox'][1]/page.rect.height})
        lines.sort(key=lambda v:v['y'])
        if sum(len(l['text']) for l in lines)<25:
            try: lines,warning=ocr_lines(full_path)
            except Exception: lines=[]; warning='本页 OCR 未成功，已保留原始截图供人工校对。'
            if warning:warnings.append(f'第 {page_index+1} 页：{warning}')
            warnings.append('OCR 文本仅作草稿，数学公式请对照原始截图确认。')
        starts=[(i,QUESTION.match(l['text'])) for i,l in enumerate(lines) if QUESTION.match(l['text'])]
        if not starts:
            if current is not None and lines:
                current['text']+='\n'+'\n'.join(l['text'] for l in lines);current['images'].append(image_name)
            else:
                current={'number':f'待拆分·页{page_index+1}','text':'\n'.join(l['text'] for l in lines),'images':[image_name]};questions.append(current)
            continue
        with Image.open(full_path) as image:
            for n,(idx,match) in enumerate(starts):
                # Save leading continuation on its preceding question, never discard it.
                if n==0 and idx>0 and current is not None:
                    leading='\n'.join(l['text'] for l in lines[:idx])
                    current['text']+='\n'+leading
                    cropname=f'continuation-{page_index+1}.png'
                    image.crop((0,0,image.width,int(max(0.02,lines[idx]['y'])*image.height))).save(out_dir/cropname)
                    current['images'].append(cropname)
                next_idx=starts[n+1][0] if n+1<len(starts) else len(lines)
                top=max(0,lines[idx]['y']-0.015)
                bottom=max(top+0.02,lines[next_idx]['y']-0.005) if next_idx<len(lines) else 1
                cropname=f'question-{page_index+1}-{n+1}.png'
                image.crop((0,int(top*image.height),image.width,min(image.height,int(bottom*image.height)))).save(out_dir/cropname)
                current={'number':match.group(1),'text':'\n'.join(l['text'] for l in lines[idx:next_idx]),'images':[cropname]}
                questions.append(current)
    if not questions:raise ValueError('试卷为空。')
    warnings.append('自动题号识别可能将小题当作大题；导入后需人工检查、合并或拆分。')
    return questions,list(dict.fromkeys(warnings))

def docx_extract(path,out_dir):
    # Bound archive expansion before python-docx opens it.
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist()
        if len(infos)>3000 or sum(v.file_size for v in infos)>100_000_000:raise ValueError('DOCX 解压体积过大。')
    soffice=os.environ.get('LIBREOFFICE_CMD') or shutil.which('libreoffice') or shutil.which('soffice')
    if not soffice and os.name=='nt':
        candidate=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'LibreOffice/program/soffice.exe'
        if candidate.exists():soffice=str(candidate)
    if soffice:
        profile=(out_dir/'lo-profile').resolve().as_uri()
        r=subprocess.run([soffice,f'-env:UserInstallation={profile}','--headless','--convert-to','pdf','--outdir',str(out_dir),str(path)],timeout=55,capture_output=True)
        pdf=out_dir/(path.stem+'.pdf')
        if r.returncode==0 and pdf.exists():return pdf_extract(pdf,out_dir)
    from docx import Document
    doc=Document(path); questions=[];current=None; warnings=['本机没有可用的 LibreOffice 转换器：DOCX 已提取文字与内嵌图片，但未生成原版式截图。请安装 LibreOffice 或导入另存的 PDF。','DOCX 中的 Office 数学公式未转成可信表达式，请以原始文件为准。']
    for p in doc.paragraphs:
        text=p.text
        # Preserve visible formula text from OMML as labelled raw fragments, not fake LaTeX.
        omml=p._p.xpath('.//m:oMath')
        if omml:text+='\n[Office公式原始文本：'+ ' | '.join(''.join(el.itertext()) for el in omml)+']'
        m=QUESTION.match(text)
        if m or current is None:
            current={'number':m.group(1) if m else '待拆分','text':text,'images':[]};questions.append(current)
        else:current['text']+='\n'+text
    for table in doc.tables:
        if current is None:
            current={'number':'待拆分','text':'','images':[]};questions.append(current)
        current['text']+='\n'+'\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows)
    for i,rel in enumerate(doc.part.rels.values()):
        if 'image' in rel.reltype and not rel.is_external:
            try:
                from io import BytesIO
                with Image.open(BytesIO(rel.target_part.blob)) as image:
                    name=f'docx-image-{i}.png';image.convert('RGB').save(out_dir/name)
                    if questions:questions[0]['images'].append(name)
            except Exception:pass
    if not questions:raise ValueError('DOCX 未发现可读取内容，请先另存为 PDF。')
    return questions,warnings

def main():
    if os.name!='nt':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(110,115))
        resource.setrlimit(resource.RLIMIT_AS,(1024*1024*1024,1024*1024*1024))
    req=json.loads(sys.stdin.read(64000)); path=Path(req['path']);out_dir=path.parent
    try:
        if path.suffix=='.pdf': questions,warnings=pdf_extract(path,out_dir)
        else: questions,warnings=docx_extract(path,out_dir)
        if len(questions)>250:raise ValueError('识别题目超过 250 道，请拆分试卷文件。')
        print(json.dumps({'ok':True,'questions':questions,'warnings':warnings},ensure_ascii=False))
    except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False))

if __name__=='__main__':main()
