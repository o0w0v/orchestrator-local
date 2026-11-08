"""Short first-run/upgrade wizard; normal use returns to the ON/OFF window."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from .setup_flow import apply_setup, inspect_setup


class SetupWizard:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Orchestrator Local セットアップ')
        self.window.geometry('680x540');self.window.minsize(640,520)
        self.window.transient(app.root)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.plan = None;self.page = 0;self.busy = False;self.closed = False
        frame = ttk.Frame(self.window,padding=28);frame.pack(fill='both',expand=True)
        self.heading = tk.StringVar(value='現在の環境を確認しています…')
        ttk.Label(frame,textvariable=self.heading,font=('Yu Gothic UI',18,'bold')).pack(anchor='w',pady=(0,12))
        self.body = ttk.Frame(frame);self.body.pack(fill='both',expand=True)
        self.error = tk.StringVar()
        ttk.Label(frame,textvariable=self.error,wraplength=600,foreground='#a52020').pack(fill='x',pady=8)
        row=ttk.Frame(frame);row.pack(fill='x')
        self.back=ttk.Button(row,text='戻る',command=self.go_back);self.back.pack(side='left')
        self.next=ttk.Button(row,text='次へ',command=self.advance,style='Primary.TButton');self.next.pack(side='right')
        self.next.state(['disabled']);self.back.state(['disabled'])
        app.run(lambda:inspect_setup(app.controller),callback=self.discovered,error_callback=self.failed)

    def discovered(self,plan):
        if self.closed:return
        self.plan=plan
        self.data=tk.StringVar(value=plan['data_dir']);self.ollama=tk.StringVar(value=plan['ollama_exe'])
        self.models=tk.StringVar(value=plan['models']);self.startup=tk.BooleanVar(value=plan['auto_start'])
        self.show()

    def text(self,value):
        ttk.Label(self.body,text=value,wraplength=590,justify='left').pack(anchor='w',pady=(4,12))

    def show(self):
        for widget in self.body.winfo_children():widget.destroy()
        self.error.set('');self.next.state(['!disabled'])
        self.back.state(['disabled'] if self.page in {0,3} else ['!disabled'])
        if self.page==0:
            self.heading.set('Orchestrator Local を使えるようにする')
            self.text('いつものCodexへの依頼はそのまま。データ作業や小さなアプリのコード案をPC内のAIに分担します。')
            self.text('以前の導入を見つけました。保存先・モデルの場所・作業履歴を引き継いで更新します。旧版での登録解除は不要です。' if self.plan['existing'] else '必要な場所を確認し、Codexへの接続をまとめて設定します。管理者権限は不要です。')
            self.text('OllamaとGemma4:26bは既存のものを使います。モデルやOllamaを勝手にダウンロードすることはありません。')
            self.next.configure(text='次へ')
        elif self.page==1:
            self.heading.set('使う場所を確認する')
            self.text('検出した設定を表示しています。そのままでよければ「次へ」を押してください。')
            for label,var,is_file in [('成果物・履歴の保存先',self.data,False),('Ollama',self.ollama,True),('モデルの場所（通常は空欄）',self.models,False)]:
                ttk.Label(self.body,text=label).pack(anchor='w')
                row=ttk.Frame(self.body);row.pack(fill='x',pady=(2,10))
                entry=ttk.Entry(row,textvariable=var);entry.pack(side='left',fill='x',expand=True)
                button=ttk.Button(row,text='変更',command=lambda v=var,f=is_file:self.choose(v,f));button.pack(side='right',padx=(8,0))
                if self.plan['existing']:entry.state(['readonly']);button.state(['disabled'])
            ttk.Checkbutton(self.body,text='PCへのログイン時に待機サービスを起動する',variable=self.startup).pack(anchor='w',pady=6)
            self.next.configure(text='次へ')
        elif self.page==2:
            self.heading.set('設定を適用する')
            self.text('次の内容で設定します。')
            self.text('・以前の設定とSkillをバックアップ\n・Codex接続をこの版へ登録\n・成果物と作業履歴を保持\n・ローカル分担はOFFで開始')
            self.text('保存先：'+self.data.get())
            self.text('作業中の依頼がある場合は更新を止めます。設定だけではAIの生成を始めません。')
            self.next.configure(text='インストールする')
        else:
            self.heading.set('セットアップが完了しました')
            self.text('ローカルの実行サービスとCodex接続を登録しました。')
            self.text('1. Codexを再起動して、新しい会話を開く\n2. Orchestrator LocalをONにする\n3. いつもどおり、資料と作業内容をCodexへ依頼する')
            self.text('例：「このJSONを集計して、一覧と短い報告文を作って」\n不要なときはOFFにするか、会話で「今回は使わない」と伝えてください。')
            self.next.configure(text='ON/OFF画面を開く')

    def choose(self,var,is_file):
        value=filedialog.askopenfilename(parent=self.window,filetypes=[('Ollama','ollama.exe')]) if is_file else filedialog.askdirectory(parent=self.window)
        if value:var.set(value)

    def advance(self):
        if self.busy or self.plan is None:return
        if self.page==1 and (not Path(self.ollama.get()).is_file() or (self.models.get() and not Path(self.models.get()).is_dir())):
            self.error.set('Ollamaまたはモデルの場所が見つかりません。「変更」から既存の場所を選んでください。');return
        if self.page==2:
            self.busy=True;self.next.state(['disabled']);self.back.state(['disabled'])
            self.heading.set('設定しています…')
            values=(self.plan,self.data.get(),self.ollama.get(),self.models.get(),self.startup.get())
            self.app.run(lambda:apply_setup(self.app.controller,*values),callback=self.completed,error_callback=self.failed)
        elif self.page==3:self.close()
        else:self.page+=1;self.show()

    def completed(self,receipt):
        self.busy=False;self.page=3;self.show()
        self.app.initial_fields=False;self.app.refresh()

    def failed(self,message):
        if self.closed:return
        self.busy=False;self.error.set(message)
        self.heading.set('設定を確認してください')
        self.next.state(['!disabled'] if self.plan else ['disabled'])
        self.back.state(['!disabled'] if self.plan and self.page else ['disabled'])

    def go_back(self):
        if not self.busy and self.page:self.page-=1;self.show()

    def close(self):
        if self.busy:return
        self.closed=True
        self.window.destroy();self.app.wizard=None
        self.app.toggle_details(False)
