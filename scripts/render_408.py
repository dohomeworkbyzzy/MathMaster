"""Development import step: render sanitized, offline exam pages with local diagrams."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
papers=json.loads((ROOT/'artifacts/grading-acceptance/408-import.json').read_text(encoding='utf-8'))
with sync_playwright() as p:
    executables=list((Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'ms-playwright').glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    browser=p.chromium.launch(executable_path=str(sorted(executables)[-1]) if executables else None,headless=True)
    page=browser.new_page(viewport={'width':1100,'height':900},device_scale_factor=1.5)
    page.route('http://**/*',lambda route:route.abort());page.route('https://**/*',lambda route:route.abort())
    for paper in papers:
        folder=ROOT/'data/uploads'/paper['id']
        page.goto((folder/'paper.html').as_uri(),wait_until='load')
        page.evaluate('Promise.all([...document.images].map(img=>img.decode()))')
        for q in paper['questions']:
            if q['images']:
                path=ROOT/'data/uploads'/q['images'][0]
                if not path.exists():page.locator('#q'+str(q['number']).zfill(2)).screenshot(path=str(path))
        pdf=folder/'paper.pdf'
        if not pdf.exists():page.pdf(path=str(pdf),format='A4',print_background=True,margin={'top':'12mm','bottom':'12mm','left':'12mm','right':'12mm'},display_header_footer=False)
        print(paper['id'],'rendered',flush=True)
    browser.close()
