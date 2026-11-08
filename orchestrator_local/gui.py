"""Small Windows setup/status UI. All network and service work stays off Tk's thread."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime
import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .desktop import DesktopController, discover_ollama
from .paths import default_data_dir, resource_root

STATES = {'QUEUED': '待機中', 'RUNNING': '作業中', 'CANDIDATE_READY': 'AIの確認待ち',
          'COMPLETED': '完了', 'CANCELLED': '中止', 'INTERRUPTED': '中断', 'FAILED': '失敗'}
FONT = 'Yu Gothic UI'


class App:
    def __init__(self, root, controller=None, auto_refresh=True):
        self.root = root
        self.controller = controller or DesktopController()
        self.auto_refresh = auto_refresh
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='desktop')
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.state = {'configured': False, 'jobs': []}
        self.initial_fields = False
        self.wizard = None
        self.setup_requested = False
        self.refresh_timer = None
        self.action_buttons = []
        root.title('Orchestrator Local')
        root.geometry('560x400'); root.minsize(520, 380)
        root.configure(bg='#f3f5f9')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=(FONT, 10), background='#f3f5f9', foreground='#19283c')
        style.configure('TButton', padding=(14, 9), background='#e4eaf3', borderwidth=0)
        style.map('TButton', background=[('active', '#d5dfed')])
        style.configure('Primary.TButton', background='#245fc4', foreground='white')
        style.map('Primary.TButton', background=[('active', '#194b9f'), ('disabled', '#9fb4d8')])
        style.configure('Title.TLabel', font=(FONT, 20, 'bold'))
        style.configure('Subtitle.TLabel', foreground='#56647b')
        style.configure('Card.TFrame', background='white')
        style.configure('Card.TLabel', background='white')
        style.configure('CardTitle.TLabel', background='white', font=(FONT, 13, 'bold'))
        style.configure('Treeview', background='white', fieldbackground='white', rowheight=34, borderwidth=0)
        style.configure('Treeview.Heading', font=(FONT, 10, 'bold'), padding=8)
        style.configure('TNotebook.Tab', padding=(18, 10))
        header = ttk.Frame(root, padding=(26, 20, 26, 12)); header.pack(fill='x')
        ttk.Label(header, text='Orchestrator Local', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='いつものAIへの頼み方はそのまま。PC内のAIと作業を分担。', style='Subtitle.TLabel').pack(anchor='w', pady=(4, 0))
        self.home = ttk.Frame(root, padding=(24, 4, 24, 8)); self.home.pack(fill='x')
        self.details = ttk.Frame(root, padding=(24, 0, 24, 0))
        self.button(self.details, '← ON/OFFに戻る', self.toggle_details).pack(anchor='w', pady=(0, 8))
        self.tabs = ttk.Notebook(self.details); self.tabs.pack(fill='both', expand=True)
        self.history = ttk.Frame(self.tabs, padding=16)
        self.setup_page = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(self.setup_page, text='設定'); self.tabs.add(self.history, text='履歴')
        self.message = tk.StringVar(value='状態を確認しています…')
        ttk.Label(root, textvariable=self.message, style='Subtitle.TLabel', wraplength=500, padding=(26, 8)).pack(side='bottom', fill='x')
        self._home(); self._history(); self._setup()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self._drain)
        self.refresh()

    def button(self, parent, text, command, primary=False):
        b = ttk.Button(parent, text=text, command=command, style='Primary.TButton' if primary else 'TButton')
        self.action_buttons.append(b)
        return b

    def _home(self):
        card = ttk.Frame(self.home, style='Card.TFrame', padding=18); card.pack(fill='x')
        self.headline = tk.StringVar(value='準備状況を確認中')
        self.detail = tk.StringVar()
        ttk.Label(card, textvariable=self.headline, style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(card, textvariable=self.detail, style='Card.TLabel', wraplength=450).pack(anchor='w', pady=(8, 14))
        row = ttk.Frame(card, style='Card.TFrame'); row.pack(fill='x')
        self.dispatch_button = self.button(row, 'ONにする', self.toggle_dispatch, True)
        self.dispatch_button.pack(side='left', padx=(0, 8))
        self.button(row, '詳細', self.toggle_details).pack(side='left')
        ttk.Label(self.home, text='普段の依頼と結果の受け取りはCodexの会話で。\nONでも「今回は使わない」という指示を優先します。\n切り替えは同じ保存先を使う会話で共通です。',
                  style='Subtitle.TLabel', wraplength=480).pack(anchor='w', pady=(12, 0))

    def toggle_details(self, show=None):
        show = not bool(self.details.winfo_manager()) if show is None else show
        if show:
            self.home.pack_forget()
            self.details.pack(fill='both', expand=True)
            self.root.minsize(880, 720); self.root.geometry('1000x800')
        else:
            self.details.pack_forget()
            self.home.pack(fill='x')
            self.root.minsize(520, 380); self.root.geometry('560x400')

    def open_setup(self):
        if self.wizard is not None:
            self.wizard.window.lift();return
        from .setup_wizard import SetupWizard
        self.wizard = SetupWizard(self)

    def toggle_dispatch(self):
        if not self.state['configured']:
            self.open_setup(); return
        enabled = not self.state['local_dispatch']['enabled']
        if enabled and self.state.get('connection') != 'registered':
            self.open_setup(); return
        message = 'ローカル分担をONにしました。' if enabled else 'ローカル分担をOFFにしました。通常のCodexで処理します。'
        self.run(lambda: self.controller.set_enabled(enabled), message)

    def _history(self):
        ttk.Label(self.history, text='最近の作業（最大200件）', font=(FONT, 13, 'bold')).pack(anchor='w', pady=(0, 12))
        table = ttk.Frame(self.history); table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('time', 'title', 'state'), show='headings', selectmode='browse')
        for key, label, width in [('time', '受付', 125), ('title', '依頼内容', 540), ('state', '状態', 150)]:
            self.tree.heading(key, text=label); self.tree.column(key, width=width, minwidth=80, stretch=key == 'title')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set); scroll.pack(side='right', fill='y'); self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self._selected_detail())
        self.job_detail = tk.StringVar(value='作業を選択してください。')
        ttk.Label(self.history, textvariable=self.job_detail, wraplength=860).pack(anchor='w', pady=12)
        row = ttk.Frame(self.history); row.pack(fill='x')
        self.button(row, '完成した成果物を開く', lambda: self.open_folder('result')).pack(side='left', padx=(0, 8))
        self.button(row, '選択した作業を中止', self.cancel).pack(side='left')
        row = ttk.Frame(self.history); row.pack(fill='x', pady=(8, 0))
        self.button(row, '入力ファイルを追加', self.import_inputs).pack(side='left', padx=(0, 8))
        self.button(row, '入力フォルダを開く', lambda: self.open_folder('inbox')).pack(side='left', padx=(0, 8))
        self.button(row, 'サンプル依頼文をコピー', self.copy_example).pack(side='left')

    def _setup(self):
        ttk.Label(self.setup_page, text='最初の一度だけ、接続と保存先を設定します。', font=(FONT, 13, 'bold')).pack(anchor='w')
        ttk.Label(self.setup_page, text='現在の自動登録先はCodexのMCP・Skillです。登録後に接続を再起動し、新しい会話を開いてください。', wraplength=860, style='Subtitle.TLabel').pack(anchor='w', pady=(6, 14))
        self.data_dir = tk.StringVar(value=str(default_data_dir()))
        self.ollama_exe = tk.StringVar(value=discover_ollama())
        self.models = tk.StringVar()
        fields = ttk.Frame(self.setup_page); fields.pack(fill='x')
        fields.columnconfigure(1, weight=1)
        self.fields = []
        for i, (label, variable, is_file) in enumerate([('成果物の保存先', self.data_dir, False), ('既存のOllama', self.ollama_exe, True), ('モデルの場所（任意）', self.models, False)]):
            ttk.Label(fields, text=label).grid(row=i, column=0, sticky='w', pady=8, padx=(0, 14))
            entry = ttk.Entry(fields, textvariable=variable); entry.grid(row=i, column=1, sticky='ew', pady=8)
            choose = self.button(fields, '選択', lambda v=variable, f=is_file: self.choose(v, f)); choose.grid(row=i, column=2, padx=(8, 0))
            self.fields.extend([entry, choose])
        ttk.Label(self.setup_page, text='モデルを標準の場所に置いている場合、モデルの場所は空欄で構いません。\nOllamaやモデルを自動ダウンロードすることはありません。', style='Subtitle.TLabel').pack(anchor='w', pady=8)
        self.autostart = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.setup_page, text='PCへのログイン時に実行サービスを自動起動する', variable=self.autostart).pack(anchor='w', pady=8)
        row = ttk.Frame(self.setup_page); row.pack(fill='x', pady=8)
        self.button(row, '初期設定・接続登録', self.setup, True).pack(side='left', padx=(0, 8))
        self.button(row, '自動起動の設定を適用', self.apply_startup).pack(side='left')
        self.connection = tk.StringVar(value='未設定')
        ttk.Label(self.setup_page, textvariable=self.connection, wraplength=860).pack(anchor='w', pady=10)
        row = ttk.Frame(self.setup_page); row.pack(fill='x', pady=8)
        self.button(row, '接続登録を解除', self.unregister).pack(side='left', padx=(0, 8))
        self.button(row, '実行サービスを起動', self.start).pack(side='left', padx=(0, 8))
        self.button(row, '実行サービスを停止', self.stop).pack(side='left', padx=(0, 8))
        self.button(row, 'ログフォルダを開く', lambda: self.open_folder('logs')).pack(side='left', padx=(0, 8))
        self.button(row, '使い方を開く', lambda: webbrowser.open('https://github.com/o0w0v/orchestrator-local#readme')).pack(side='left')
        ttk.Label(self.setup_page, text='設定ファイル：' + str(self.controller.config), style='Subtitle.TLabel', wraplength=860).pack(anchor='w', pady=8)
        ttk.Label(self.setup_page, text='「初期設定・接続登録」で案内に沿って更新できます。成果物は残ります。\nこの画面を閉じても、起動済みの実行サービスは動き続けます。', style='Subtitle.TLabel').pack(anchor='w', pady=4)

    def choose(self, variable, is_file):
        value = filedialog.askopenfilename(parent=self.root, title='既存のollama.exeを選択', filetypes=[('Ollama', 'ollama.exe')]) if is_file else filedialog.askdirectory(parent=self.root)
        if value: variable.set(value)

    def run(self, operation, success='', callback=None, error_callback=None):
        if self.busy or self.closed: return
        self.busy = True
        for b in self.action_buttons: b.state(['disabled'])
        if success: self.message.set('処理しています…')
        def work():
            try: self.events.put((True, operation(), success, callback))
            except Exception as exc: self.events.put((False, str(exc), '', error_callback))
        self.executor.submit(work)

    def _drain(self):
        if self.closed: return
        try:
            ok, result, success, callback = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for b in self.action_buttons: b.state(['!disabled'])
            if ok:
                if success: self.message.set(success)
                if callback: callback(result)
                if success: self.refresh()
            else:
                self.message.set('処理を完了できませんでした。')
                if callback: callback(result)
                else: messagebox.showerror('Orchestrator Local', result, parent=self.root)
        self.root.after(100, self._drain)

    def refresh(self):
        if self.closed: return
        if self.refresh_timer:
            self.root.after_cancel(self.refresh_timer); self.refresh_timer = None
        if self.busy:
            self.schedule_refresh(); return
        def snapshot():
            value = self.controller.snapshot()
            if not self.initial_fields: value['startup'] = self.controller.startup()
            return value
        self.run(snapshot, callback=self.render)

    def schedule_refresh(self):
        if self.auto_refresh and not self.closed:
            if self.refresh_timer: self.root.after_cancel(self.refresh_timer)
            self.refresh_timer = self.root.after(5000, self.refresh)

    def render(self, state):
        self.state = state
        if not state['configured']:
            self.headline.set('初回設定が必要です')
            self.dispatch_button.configure(text='初回設定')
            self.detail.set('初回設定の後は、この画面のON/OFFだけで切り替えられます。')
        else:
            enabled = state['local_dispatch']['enabled']
            running = state['service']['ready']
            connected = state['connection'] == 'registered'
            self.dispatch_button.configure(text='OFFにする' if enabled else ('ONにする' if connected else '初回設定'))
            self.headline.set('ローカル分担 ON' if enabled else 'ローカル分担 OFF')
            if enabled:
                detail = '対応する作業では、必要に応じてPC内のGemmaへ分担します。'
                if not connected: detail = '接続登録が必要です。「詳細」の設定を確認してください。'
                elif not running: detail = '実行サービスが停止しています。「詳細」で起動できます。'
                elif state['service'].get('control_version') != 1: detail = '旧版サービスが動作中です。「詳細」で停止してからONにしてください。'
                backend = state['backend'] or {}
                if backend.get('reachable') and not backend.get('digest_matches'):
                    detail = '設定したモデルがないか、版が異なります。「詳細」の設定を確認してください。'
            else:
                detail = '新しいGemma作業は始めず、通常のCodexで処理します。'
            control = state['local_dispatch']
            if not enabled and (control['running'] or control['queued']):
                detail += f"\n進行中{control['running']}件は継続し、待機{control['queued']}件はONまで保留します。"
            self.detail.set(detail)
            label = {'registered': 'この導入先の接続を登録済み', 'missing': '接続未登録', 'other_installation': '以前の導入が見つかりました。「初期設定・接続登録」で引き継げます。', 'invalid': '接続設定を読み取れませんでした。'}[state['connection']]
            self.connection.set(label)
            if not self.initial_fields:
                saved = state['settings']; self.data_dir.set(saved['data_dir']); self.ollama_exe.set(saved.get('ollama_exe', '')); self.models.set(saved.get('ollama_environment', {}).get('OLLAMA_MODELS', ''))
            for field in self.fields: field.state(['disabled'])
        if not self.initial_fields:
            self.autostart.set(state.get('startup', False))
            if self.auto_refresh and state['configured'] and state['local_dispatch']['enabled'] and not state['service']['ready'] and state['connection'] == 'registered':
                self.root.after_idle(self.start)
        self.initial_fields = True
        if self.auto_refresh and not self.setup_requested and (not state['configured'] or state.get('connection') != 'registered'):
            self.setup_requested = True
            self.root.after_idle(self.open_setup)
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for job in state['jobs']:
            status = '中止要求済み' if job['cancel'] and job['state'] in {'QUEUED', 'RUNNING'} else STATES.get(job['state'], job['state'])
            self.tree.insert('', 'end', iid=job['id'], values=(datetime.fromtimestamp(job['created']).strftime('%m/%d %H:%M'), job['title'], status))
        if selection and self.tree.exists(selection[0]): self.tree.selection_set(selection[0])
        self._selected_detail()
        if self.message.get() == '状態を確認しています…':
            self.message.set('初回設定を行ってください。' if not state['configured'] else '状態を更新しました。')
        self.schedule_refresh()

    def selected(self):
        selection = self.tree.selection()
        return next((j for j in self.state['jobs'] if selection and j['id'] == selection[0]), None)

    def _selected_detail(self):
        job = self.selected()
        self.job_detail.set((job.get('error') or job.get('phase') or '') if job else '作業を選択してください。')

    def start(self):
        if not self.state['configured']: self.open_setup(); return
        self.run(self.controller.start_service, '実行サービスを起動しました。待機中は生成しません。')

    def stop(self):
        active = any(j['state'] in {'QUEUED', 'RUNNING'} for j in self.state['jobs'])
        if active and not messagebox.askyesno('実行サービスを停止', '作業中の処理に中止を要求して停止します。停止しますか？', parent=self.root): return
        self.run(self.controller.stop_service, '実行サービスを停止しました。')

    def cancel(self):
        job = self.selected()
        if not job or job['state'] not in {'QUEUED', 'RUNNING'}:
            self.message.set('待機中・作業中の依頼を選択してください。'); return
        if messagebox.askyesno('作業を中止', '選択した作業の中止を要求します。自動で再生成はしません。続けますか？', parent=self.root):
            self.run(lambda: self.controller.cancel_job(job['id']), '選択した作業に中止を要求しました。')

    def setup(self):
        self.open_setup()

    def unregister(self):
        if messagebox.askyesno('接続登録を解除', 'この導入先のMCP・Skill登録を解除します。成果物は残ります。自動起動は別のチェック欄で解除できます。続けますか？', parent=self.root):
            self.run(self.controller.remove_connection, '接続登録を解除しました。Codexの接続を再起動してください。')

    def apply_startup(self):
        enabled = self.autostart.get()
        self.run(lambda: self.controller.set_startup(enabled), '自動起動の設定を保存しました。')

    def import_inputs(self):
        if not self.state['configured']: self.open_setup(); return
        paths = filedialog.askopenfilenames(parent=self.root, title='入力資料を選択', filetypes=[('対応資料', '*.csv *.json *.txt *.md')])
        if paths: self.run(lambda: self.controller.import_inputs(paths), '入力資料を追加しました。会話でファイル名と依頼内容を伝えてください。')

    def open_folder(self, kind):
        job = self.selected()
        if kind == 'result' and not job: self.message.set('作業を選択してください。'); return
        def open_it():
            path = self.controller.folder(kind, job['id'] if job else None)
            os.startfile(str(path))
        self.run(open_it, 'フォルダを開きました。')

    def copy_example(self):
        text = (resource_root() / 'examples/first-request.md').read_text(encoding='utf8')
        self.root.clipboard_clear(); self.root.clipboard_append(text)
        self.message.set('サンプルの依頼文をコピーしました。いつもの会話に貼り付けてください。')

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config'); p.add_argument('--codex-config'); p.add_argument('--skill-root'); p.add_argument('--startup-dir')
    p.add_argument('--check-ui', help='Build verification: render without user actions, write a report and exit')
    p.add_argument('--setup', action='store_true', help='Open the guided first-run/upgrade setup')
    args = p.parse_args()
    if args.check_ui and not all((args.config, args.codex_config, args.skill_root, args.startup_dir)):
        p.error('--check-ui requires explicit temporary config, codex-config, skill-root and startup-dir')
    root = tk.Tk()
    if args.check_ui: root.withdraw()
    app = App(root, DesktopController(args.config, args.codex_config, args.skill_root, args.startup_dir), auto_refresh=not args.check_ui)
    if args.setup:
        def setup_when_ready():
            if app.busy: root.after(100,setup_when_ready)
            else:
                app.setup_requested=True;app.open_setup()
        root.after(150,setup_when_ready)
    if args.check_ui:
        def report():
            if app.busy:
                root.after(100, report); return
            import json
            root.update_idletasks()
            Path(args.check_ui).write_text(json.dumps({'title': root.title(), 'configured': app.state['configured'],
                'headline': app.headline.get(), 'jobs': len(app.tree.get_children()),
                'states': [app.tree.item(j)['values'][-1] for j in app.tree.get_children()],
                'home_requested_height': app.home.winfo_reqheight(), 'setup_requested_height': app.setup_page.winfo_reqheight(),
                'details_hidden': not bool(app.details.winfo_manager()), 'toggle_label': app.dispatch_button['text'],
                'local_enabled': app.state.get('local_dispatch', {}).get('enabled', False),
                'tabs': [app.tabs.tab(t, 'text') for t in app.tabs.tabs()]}, ensure_ascii=False), encoding='utf8')
            app.close()
        root.after(100, report)
    root.mainloop()
