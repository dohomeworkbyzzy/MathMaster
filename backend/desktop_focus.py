"""Recognize the workspace's own titles without depending on its visual skin."""

BROWSERS = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe',
            'vivaldi.exe', 'opera.exe'}

# Keep these exact titles in sync with web/Appearance.tsx. Do not allow generic
# "Word", "Excel", or "Visual Studio Code" matches: other windows must be ignored.
WORKSPACE_TITLES = (
    'analysis.py - workspace - Visual Studio Code',
    '项目分析记录.docx - Word',
    '数据分析工作簿.xlsx - Excel',
)


def workspace_title(title):
    if 'MathMaster' in title:
        return True
    return any(title == own or title.startswith(own + ' - ') or
               title.startswith(own + ' — ') for own in WORKSPACE_TITLES)


def workspace_window(title, executable):
    name = executable.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return name in BROWSERS and workspace_title(title)
