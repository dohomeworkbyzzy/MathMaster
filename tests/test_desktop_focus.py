import re
from pathlib import Path

import pytest

from backend.desktop_focus import workspace_window


def test_every_frontend_skin_title_is_accepted_by_native_browser_focus_gate():
    source = (Path(__file__).resolve().parents[1] / 'web' / 'Appearance.tsx').read_text(encoding='utf-8')
    declaration = re.search(r'const documentTitles[^=]*=\{([^}]+)\}', source)
    assert declaration, 'Cannot find frontend window titles'
    titles = re.findall(r"\w+:'([^']+)'", declaration.group(1))
    assert len(titles) == 4
    for title in titles:
        for suffix in ('', ' - Google Chrome', ' — Mozilla Firefox', ' - 个人 - Microsoft Edge'):
            assert workspace_window(title + suffix, r'C:\Program Files\Browser\msedge.exe')


@pytest.mark.parametrize(('title', 'executable'), [
    ('项目进度周报.docx - Word', 'msedge.exe'),  # F8 cover must release capture.
    ('其他文档.docx - Word', 'chrome.exe'),
    ('其他工作簿.xlsx - Excel', 'msedge.exe'),
    ('Visual Studio Code', 'chrome.exe'),
    ('项目分析记录.docx - Word', 'WINWORD.EXE'),
    ('数据分析工作簿.xlsx - Excel', 'EXCEL.EXE'),
    ('analysis.py - workspace - Visual Studio Code', 'Code.exe'),
    ('MathMaster', 'notepad.exe'),
    ('', 'chrome.exe'),
])
def test_other_apps_tabs_and_cover_are_rejected(title, executable):
    assert not workspace_window(title, executable)
