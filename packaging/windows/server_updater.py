"""Offline Windows updater: complete runtime swaps, with state kept in place."""
import argparse
from contextlib import closing, contextmanager
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parent))
import library_update

PRODUCT = 'mathmaster-server'
MAX_SIZE = 2_000_000_000


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_manifest(archive):
    """Accept only complete, hash-addressed program files, never user state."""
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(name.casefold() for name in names)):
        raise ValueError('更新包有重复文件。')
    if sum(entry.file_size for entry in entries) > MAX_SIZE:
        raise ValueError('更新包过大。')
    if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 2_000_000:
        raise ValueError('缺少更新清单。请选择 master-release 更新包。')
    manifest = json.loads(archive.read('manifest.json'))
    if manifest.get('format') != 1 or manifest.get('product') != PRODUCT:
        raise ValueError('这不是兼容的 master 服务更新包。')
    files = manifest.get('files')
    if not isinstance(files, dict) or set(files) != set(names) - {'manifest.json'}:
        raise ValueError('更新包文件与清单不一致。')
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if (not name or '\\' in name or ':' in name or path.is_absolute()
                or any(part in ('', '.', '..') for part in name.split('/'))
                or (entry.external_attr >> 16) & 0o170000 == 0o120000):
            raise ValueError('更新包包含不安全的文件路径。')
        if name == 'manifest.json':
            continue
        if name != 'master.exe' and not name.startswith('_internal/'):
            raise ValueError('更新包试图修改程序目录以外的文件。')
        value = files[name]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('更新包校验信息无效。')
    if not {'master.exe', '_internal/dist/index.html'} <= set(files):
        raise ValueError('更新包缺少完整的前后端程序。')
    if not isinstance(manifest.get('version'), str) or len(manifest['version']) > 100:
        raise ValueError('更新包版本无效。')
    routes = manifest.get('required_routes', [])
    if not isinstance(routes, list) or not all(isinstance(route, str) for route in routes):
        raise ValueError('更新包接口清单无效。')
    return manifest


def extract_verified(package, destination, report):
    with zipfile.ZipFile(package) as archive:
        manifest = read_manifest(archive)
        total = len(manifest['files'])
        for index, (name, expected) in enumerate(manifest['files'].items(), 1):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            if digest(target) != expected:
                raise ValueError('更新包损坏，校验失败：' + name)
            if index % 100 == 0:
                report(f'校验程序文件 {index}/{total}')
        return manifest


def running(root):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    key = hashlib.sha256(str(root).lower().encode()).hexdigest()[:24]
    handle = kernel.OpenMutexW(0x00100000, False, 'Local\\master-run-' + key)
    if not handle:
        error = ctypes.get_last_error()
        if error not in (0, 2):
            raise ctypes.WinError(error)
        return False
    kernel.CloseHandle(handle)
    return True


def stop(root):
    subprocess.run([str(root / 'master.exe'), '--root', str(root), '--stop'],
                   capture_output=True, check=True, timeout=20,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 45
    while running(root):
        if time.monotonic() >= deadline:
            raise RuntimeError('服务未能正常停止，未强制结束进程。请关闭服务窗口后重试。')
        time.sleep(.25)


@contextmanager
def update_lock(root):
    import msvcrt
    with (root / '.master-update.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('此目录已有更新任务在运行。') from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def snapshot(root, backup):
    for name in ('config.json', 'release.json'):
        source = root / name
        if source.is_file():
            shutil.copy2(source, backup / name)
    if (root / 'config').is_dir():
        shutil.copytree(root / 'config', backup / 'config')
    for source in (root / 'data').glob('*.db'):
        target = backup / 'data' / source.name
        target.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30)) as src:
            with closing(sqlite3.connect(target)) as dest:
                src.backup(dest)


def launch(root):
    return subprocess.Popen([str(root / 'master.exe'), '--root', str(root)],
                            cwd=root, creationflags=subprocess.CREATE_NEW_CONSOLE)


def move(source, target):
    # The stop event can be released a moment before Windows unmaps the EXE.
    deadline = time.monotonic() + 8
    while True:
        try:
            source.rename(target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def check_started(root, process, manifest, timeout=90):
    config = json.loads((root / 'config.json').read_text(encoding='utf-8-sig')) if (root / 'config.json').exists() else {}
    host = config.get('host', '0.0.0.0')
    if host == '0.0.0.0':
        host = '127.0.0.1'
    elif host == '::':
        host = '::1'
    if ':' in host:
        host = '[' + host + ']'
    base = f'http://{host}:{int(config.get("port", 8509))}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(base + path, timeout=2) as response:
            return response.read()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('新版服务启动后退出，请查看 logs/server.log。')
        try:
            if json.loads(get('/api/health')).get('status') == 'ok':
                paths = json.loads(get('/openapi.json'))['paths']
                if any(route not in paths for route in manifest.get('required_routes', [])):
                    raise RuntimeError('新版缺少更新包要求的接口。')
                if hashlib.sha256(get('/')).hexdigest() != manifest['files']['_internal/dist/index.html']:
                    raise RuntimeError('服务返回的前端与更新包版本不一致。')
                if process.poll() is None:
                    return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(.4)
    raise RuntimeError('新版启动检查超时，请查看 logs/server.log。')


def apply_update(package, root, report=print):
    if os.name != 'nt':
        raise RuntimeError('更新工具需要 64 位 Windows。')
    root = root.resolve()
    package = package.resolve()
    if not (root / 'master.exe').is_file() or not (root / '_internal').is_dir():
        raise ValueError('请选择现有 master.exe 所在的服务目录。')
    # Runtime junctions would move files belonging to a different installation.
    for path in (root / 'master.exe', root / '_internal', root / '.updates'):
        if path.is_symlink() or path.is_junction():
            raise ValueError('程序和备份目录不能是符号链接或目录联接。')
    with update_lock(root):
        with zipfile.ZipFile(package) as archive:
            manifest = read_manifest(archive)
            size = sum(entry.file_size for entry in archive.infolist())
        db_size = sum(p.stat().st_size for p in (root / 'data').glob('*.db*') if p.is_file())
        config_size = sum(p.stat().st_size for p in (root / 'config').rglob('*') if p.is_file())
        if shutil.disk_usage(root).free < size + db_size + config_size + 50_000_000:
            raise RuntimeError('磁盘空间不足，需容纳新版程序和数据库备份。')
        token = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
        stage = root / ('.update-stage-' + token)
        backup = root / '.updates' / token
        stage.mkdir()
        moves = []
        process = None
        was_running = False
        stopped = False
        keep_stage = False
        try:
            report('正在解压并校验更新包…')
            manifest = extract_verified(package, stage, report)
            was_running = running(root)
            report('正在停止此目录的服务…')
            stop(root)
            stopped = True
            backup.mkdir(parents=True)
            report('正在备份配置和数据库…')
            snapshot(root, backup)
            (backup / 'update.json').write_text(json.dumps({
                'version': manifest['version'], 'created_at': datetime.now(timezone.utc).isoformat(),
                'root': str(root), 'status': 'prepared'}, ensure_ascii=False, indent=2), encoding='utf-8')
            (backup / 'runtime').mkdir()
            report('正在替换前后端程序，保留题库、记录及配置…')
            for name in ('master.exe', '_internal'):
                source, target = root / name, backup / 'runtime' / name
                move(source, target)
                moves.append((source, target))
            for name in ('master.exe', '_internal'):
                source, target = stage / name, root / name
                move(source, target)
                moves.append((source, target))
            report('正在启动新版并检查页面与接口…')
            process = launch(root)
            check_started(root, process, manifest)
            # Publish version only after both backend and frontend were checked.
            release = {k: v for k, v in manifest.items() if k != 'files'}
            temp = root / '.release-new.json'
            temp.write_text(json.dumps(release, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, root / 'release.json')
            (backup / 'update.json').write_text(json.dumps({
                'version': manifest['version'], 'status': 'completed'}, indent=2), encoding='utf-8')
            report('更新完成。版本：' + manifest['version'])
            report('旧程序、配置与数据库备份：' + str(backup))
            return {'version': manifest['version'], 'backup': str(backup)}
        except Exception as error:
            try:
                if moves:
                    report('更新失败，正在恢复旧程序…')
                    if process is not None:
                        stop(root)
                        process.wait(timeout=15)
                    for source, target in reversed(moves):
                        move(target, source)
                    if (backup / 'release.json').exists():
                        shutil.copy2(backup / 'release.json', root / 'release.json')
                    else:
                        (root / 'release.json').unlink(missing_ok=True)
                if stopped and was_running:
                    launch(root)
            except Exception as recovery:
                keep_stage = True
                raise RuntimeError(f'更新失败：{error}\n自动恢复未完成：{recovery}\n请保留备份 {backup} 和暂存目录 {stage}。') from recovery
            if backup.exists():
                report('备份目录：' + str(backup))
            raise RuntimeError(str(error) + ('\n已恢复旧程序，数据库保留现状；更新前快照位于备份目录。' if moves else '')) from error
        finally:
            if not keep_stage:
                shutil.rmtree(stage, ignore_errors=True)


def apply_library(package, root, report=print):
    if os.name != 'nt':raise RuntimeError('维护工具需要 64 位 Windows。')
    root=root.resolve()
    if not (root/'master.exe').is_file() or not (root/'data/mathmaster.db').is_file():
        raise ValueError('请选择已有 master.exe 和 data/mathmaster.db 的服务目录。')
    for p in (root/'data',root/'.updates',root/'_internal'):
        if p.is_symlink() or p.is_junction():raise ValueError('服务目录不能使用链接或目录联接。')
    with update_lock(root):
        token='library-'+datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
        stage=root/('.update-stage-'+token);backup=root/'.updates'/token
        with zipfile.ZipFile(package) as archive:
            library_update.read_manifest(archive)
            size=sum(e.file_size for e in archive.infolist())
        if shutil.disk_usage(root).free < size+sum(p.stat().st_size for p in (root/'data').glob('*.db*'))+50_000_000:
            raise RuntimeError('磁盘空间不足，无法暂存和备份题库。')
        stage.mkdir();was_running=False;stopped=False;committed=False
        try:
            report('正在校验题库数据包…')
            manifest,plan=library_update.extract_verified(package,stage,report)
            required=manifest.get('required_program_version')
            if required:
                current=json.loads((root/'release.json').read_text(encoding='utf-8')) if (root/'release.json').exists() else {}
                if current.get('version','')<required:raise ValueError('请先使用此工具导入配套程序更新包，再导入题库数据包。')
            library_update.check_target(root/'data',stage,manifest)
            report(f'题库包：{len(plan["papers"])} 份资料 / {len(plan["questions"])} 题')
            was_running=running(root);stop(root);stopped=True
            backup.mkdir(parents=True);snapshot(root,backup)
            result=library_update.install_plan(root/'data',stage,manifest,plan,report);committed=True
            report('正在启动服务并检查页面…')
            process=launch(root)
            check_started(root,process,{'files':{'_internal/dist/index.html':digest(root/'_internal/dist/index.html')}})
            result['backup']=str(backup)
            (backup/'update.json').write_text(json.dumps({**result,'status':'completed'},ensure_ascii=False,indent=2),encoding='utf-8')
            report('题库维护完成，备份：'+str(backup))
            return result
        except Exception as error:
            if committed:
                report('服务检查失败，正在恢复维护前题库…')
                try:
                    stop(root)
                    source=backup/'data/mathmaster.db'
                    with closing(sqlite3.connect(root/'data/mathmaster.db')) as dst:
                        with closing(sqlite3.connect(source)) as src:src.backup(dst)
                    if was_running:launch(root)
                except Exception as recovery:
                    raise RuntimeError(f'题库维护失败：{error}；自动恢复未完成：{recovery}；备份：{backup}') from recovery
            elif stopped and was_running:launch(root)
            raise RuntimeError(f'题库维护失败：{error}；备份：{backup}') from error
        finally:shutil.rmtree(stage,ignore_errors=True)


def apply_package(package, root, report=print):
    with zipfile.ZipFile(package) as archive:
        if 'manifest.json' not in archive.namelist() or archive.getinfo('manifest.json').file_size>5_000_000:
            raise ValueError('缺少有效更新清单。')
        product=json.loads(archive.read('manifest.json')).get('product')
    if product==library_update.PRODUCT:return apply_library(package,root,report)
    return apply_update(package,root,report)


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    app = tk.Tk()
    app.title('master maintenance')
    app.geometry('740x510')
    app.minsize(640, 460)
    frame = ttk.Frame(app, padding=22)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='master 更新维护', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='支持程序更新包和题库数据包；维护前自动备份，保留用户记录与配置。').pack(anchor='w', pady=(6, 18))
    bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload.zip'
    home = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    folder = tk.StringVar(value=str(home) if (home / 'master.exe').is_file() else '')
    package_path = bundled if bundled.exists() else None
    embedded_version = ''
    if package_path:
        with zipfile.ZipFile(package_path) as archive:
            embedded_version = read_manifest(archive)['version']
    selected = tk.StringVar(value='内置新版 · ' + embedded_version if package_path else '')
    busy = False
    controls = []
    def row(label, variable, choose):
        ttk.Label(frame, text=label).pack(anchor='w')
        line = ttk.Frame(frame)
        line.pack(fill='x', pady=(4, 12))
        entry = ttk.Entry(line, textvariable=variable)
        entry.pack(side='left', fill='x', expand=True)
        button = ttk.Button(line, text='选择…', command=choose)
        button.pack(side='right', padx=(8, 0))
        controls.extend([entry, button])
        return entry
    def choose_folder():
        value = filedialog.askdirectory(title='选择 master.exe 所在的文件夹')
        if value:
            folder.set(value)
    def choose_package():
        nonlocal package_path
        value = filedialog.askopenfilename(title='选择程序更新包或题库数据包', filetypes=[('master package', '*.zip')])
        if value:
            package_path = Path(value)
            selected.set(value)
    row('现有服务目录', folder, choose_folder)
    package_entry = row('维护包（程序更新包 / 题库数据包）', selected, choose_package)
    package_entry.configure(state='readonly')
    log = tk.Text(frame, height=10, wrap='word', state='disabled', font=('Microsoft YaHei UI', 10))
    log.pack(fill='both', expand=True, pady=(0, 12))
    messages = queue.Queue()
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.pack(fill='x', pady=(0, 10))
    def start():
        nonlocal busy
        if not folder.get().strip() or package_path is None:
            messagebox.showerror('请选择目录', '请选择现有服务目录和更新包。')
            return
        target, package = Path(folder.get().strip()), package_path
        busy = True
        for control in controls:
            control.configure(state='disabled')
        update.configure(state='disabled')
        progress.start()
        def worker():
            try:
                result = apply_package(package, target, lambda text: messages.put(('log', text)))
                messages.put(('done', result))
            except Exception as error:
                messages.put(('error', str(error)))
        threading.Thread(target=worker, daemon=False).start()
    update = ttk.Button(frame, text='开始更新', command=start)
    update.pack(anchor='e')
    def poll():
        nonlocal busy
        while not messages.empty():
            kind, value = messages.get()
            if kind == 'log':
                log.configure(state='normal')
                log.insert('end', value + '\n')
                log.see('end')
                log.configure(state='disabled')
            else:
                busy = False
                progress.stop()
                for control in controls:
                    control.configure(state='normal')
                package_entry.configure(state='readonly')
                update.configure(state='normal')
                if kind == 'done':
                    messagebox.showinfo('更新完成', '新版已启动。请在浏览器按 Ctrl+F5 刷新。\n备份目录：' + value['backup'])
                else:
                    messagebox.showerror('更新未完成', value)
        app.after(150, poll)
    def close():
        if busy:
            messagebox.showinfo('正在更新', '请等待更新或恢复旧程序完成后再关闭。')
        else:
            app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    app.after(150, poll)
    app.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path)
    parser.add_argument('--package', type=Path)
    args = parser.parse_args()
    if args.root:
        package = args.package or Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload.zip'
        print(json.dumps(apply_package(package, args.root), ensure_ascii=False))
    else:
        gui()


if __name__ == '__main__':
    main()
