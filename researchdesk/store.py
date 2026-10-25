import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .catalog import TEMPLATES, Step, project_steps, resolve_workflow
from .recipes import options_valid
from dataclasses import asdict
from .providers import DEFAULTS, protect, validate_settings

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'researchdesk.sqlite3'
        self._session_key = ''
        self._profile_keys = {}
        with self.connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, title TEXT, template TEXT, goal TEXT, mode TEXT, status TEXT, cursor INTEGER, created TEXT, updated TEXT, error TEXT, skip_compute INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, project_id TEXT, created TEXT, kind TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY, project_id TEXT, step TEXT, created TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS project_config(project_id TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS role_profiles(role TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS chat_turns(project_id TEXT,turn_id TEXT,created TEXT,text TEXT,mode TEXT,status TEXT,response TEXT,error TEXT,revision INTEGER DEFAULT 1, PRIMARY KEY(project_id,turn_id));
            CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,project_id TEXT,turn_id TEXT,created TEXT,payload TEXT,status TEXT);
            ''')
            db.execute("UPDATE chat_turns SET status='interrupted',error='服务重启，本轮已中断，可用新的轮次重新发送' WHERE status IN ('running','stopping')")
            # A process restart cannot establish that a pending task finished.
            db.execute("UPDATE projects SET status='paused', error='服务重启，任务已暂停；请检查产物后继续' WHERE status='running'")
            for row in db.execute("SELECT * FROM projects WHERE status='paused'").fetchall():
                cfg=db.execute('SELECT payload FROM project_config WHERE project_id=?',(row['id'],)).fetchone()
                project=dict(row)
                if cfg: project.update(json.loads(cfg[0]))
                steps=project_steps(project)
                previous=steps[row['cursor']-1] if row['cursor'] and row['cursor']<=len(steps) else None
                if previous and (previous.id=='code' or previous.kind=='code') and not row['skip_compute']:
                    generated=db.execute('SELECT COALESCE(MAX(id),0) FROM receipts WHERE project_id=? AND step=?',(row['id'],previous.id)).fetchone()[0]
                    proof=db.execute("SELECT 1 FROM receipts WHERE project_id=? AND step='execution' AND id>?",(row['id'],generated)).fetchone()
                    if not proof:
                        db.execute("UPDATE projects SET status='awaiting_execution' WHERE id=?",(row['id'],))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally:
            db.close()

    def list(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY created DESC')]

    def get(self, pid):
        if not re.fullmatch('[a-f0-9]{32}', pid): raise ValueError('项目编号无效')
        with self.connection() as db:
            row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if row is None: raise ValueError('项目不存在')
        data=dict(row)
        with self.connection() as db:
            config=db.execute('SELECT payload FROM project_config WHERE project_id=?',(pid,)).fetchone()
        data.update(json.loads(config[0]) if config else {'options':{}})
        return data

    def create(self, title, template, goal, mode, options=None):
        title, goal = str(title).strip(), str(goal).strip()
        if not title or len(title) > 160 or not goal or len(goal) > 20000: raise ValueError('请填写项目名称（160字内）和研究目标（20000字内）')
        if template not in TEMPLATES or mode not in ('demo', 'api'): raise ValueError('项目模板或模式错误')
        if mode=='demo' and template not in ('research','competition','writing'): raise ValueError('本地演示使用独立演示流程；其他模板需要 API')
        opts=options_valid(options)
        resolved=resolve_workflow(template,opts,Step)
        if mode == 'demo':
            title = title if '演示' in title else '[演示] ' + title
            goal = '演示研究：单服务台队列的到达率如何影响等待时间。使用固定随机种子的模拟数据，无外部文献和实际观测数据。'
        pid = uuid.uuid4().hex
        with self.connection() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?,?)', (pid,title,template,goal,mode,'draft',0,now(),now(),'',0))
            config={'options':opts}
            if resolved: config['workflow']=[asdict(s) for s in resolved]
            db.execute('INSERT INTO project_config VALUES(?,?)',(pid,json.dumps(config,ensure_ascii=False)))
        for folder in ('docs','code','results','paper','materials','references','exports','audit'):
            (self.root / 'projects' / pid / folder).mkdir(parents=True, exist_ok=True)
        self.event(pid, 'info', '项目已创建；' + ('本地演示，不调用 API' if mode == 'demo' else '真实 API 项目，运行将调用你设置的接口'))
        return self.get(pid)

    def update(self, pid, **kwargs):
        allowed = {'status','cursor','error','skip_compute'}
        if set(kwargs) - allowed: raise ValueError('不允许的项目字段')
        kwargs['updated'] = now()
        with self.connection() as db:
            db.execute('UPDATE projects SET ' + ','.join(k+'=?' for k in kwargs) + ' WHERE id=?', (*kwargs.values(),pid))

    def event(self, pid, kind, message):
        with self.connection() as db:
            db.execute('INSERT INTO events(project_id,created,kind,message) VALUES(?,?,?,?)', (pid,now(),kind,str(message)[:3000]))

    def receipt(self, pid, step, payload):
        with self.connection() as db:
            db.execute('INSERT INTO receipts(project_id,step,created,payload) VALUES(?,?,?,?)', (pid,step,now(),json.dumps(payload,ensure_ascii=False)))

    def history(self, pid):
        with self.connection() as db:
            events = [dict(r) for r in db.execute('SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT 150', (pid,))]
            receipts = [dict(r) for r in db.execute('SELECT * FROM receipts WHERE project_id=? ORDER BY id', (pid,))]
        for r in receipts: r['payload'] = json.loads(r['payload'])
        return events, receipts

    def path(self, pid, relative):
        self.get(pid)
        if not isinstance(relative, str) or '\\' in relative or ':' in relative or relative.startswith('/'):
            raise ValueError('文件路径无效')
        root = (self.root / 'projects' / pid).resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or candidate == root: raise ValueError('文件越界')
        if any(p.startswith('.') for p in Path(relative).parts): raise ValueError('不允许隐藏文件路径')
        return candidate

    def write(self, pid, relative, content):
        path = self.path(pid, relative)
        if len(content.encode('utf-8')) > 2_000_000: raise ValueError('单个文本产物超过 2 MB')
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(content, encoding='utf-8', newline='\n')
        temp.replace(path)

    def files(self, pid):
        root = self.path(pid, 'docs').parent
        return [{'path': p.relative_to(root).as_posix(), 'size': p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root) and p.suffix != '.tmp']

    def settings(self, private=False):
        with self.connection() as db: row = db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        data = dict(DEFAULTS)
        if row: data.update(json.loads(row[0]))
        encrypted = data.pop('encrypted_key', '')
        data['has_key'] = bool(encrypted or self._session_key)
        data['key_storage'] = 'windows' if encrypted else 'session' if self._session_key else 'none'
        if private: data['key'] = protect(encrypted, True) if encrypted else self._session_key
        return data

    def save_settings(self, value):
        current = self.settings(private=not bool(value.get('api_key') or value.get('clear_key')))
        config = validate_settings(value)
        key = value.get('api_key', '').strip() or current.get('key','')
        if value.get('clear_key'): key = ''
        if len(key) > 4096: raise ValueError('密钥过长')
        self._session_key = ''
        try:
            config['encrypted_key'] = protect(key) if key else ''
        except ValueError:
            config['encrypted_key'] = ''
            self._session_key = key
        with self.connection() as db: db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)', (json.dumps(config),))
        return self.settings()

    def profiles(self):
        with self.connection() as db: rows=db.execute('SELECT * FROM role_profiles').fetchall()
        values={}
        for row in rows:
            data=json.loads(row['payload']);encrypted=data.pop('encrypted_key','')
            data['has_key']=bool(encrypted or self._profile_keys.get(row['role']))
            data['key_storage']='windows' if encrypted else 'session' if data['has_key'] else 'none'
            values[row['role']]=data
        return values

    def settings_for_role(self,role):
        with self.connection() as db: row=db.execute('SELECT payload FROM role_profiles WHERE role=?',(role,)).fetchone()
        if not row: return self.settings(private=True)
        data=json.loads(row[0]);encrypted=data.pop('encrypted_key','')
        data['key']=protect(encrypted,True) if encrypted else self._profile_keys.get(role,'')
        return data

    def save_profile(self,value):
        role=value.get('role')
        if role not in ('planner','coder','writer','reviewer'): raise ValueError('未知模型角色')
        if value.get('inherit'):
            with self.connection() as db: db.execute('DELETE FROM role_profiles WHERE role=?',(role,))
            self._profile_keys.pop(role,None)
            return self.profiles()
        config=validate_settings(value);config['role_models']={}
        key=str(value.get('api_key','')).strip()
        if not key and not value.get('clear_key'):
            with self.connection() as db: old=db.execute('SELECT 1 FROM role_profiles WHERE role=?',(role,)).fetchone()
            if old: key=self.settings_for_role(role).get('key','')
        if value.get('clear_key'): key=''
        if len(key)>4096: raise ValueError('密钥过长')
        self._profile_keys.pop(role,None)
        try: config['encrypted_key']=protect(key) if key else ''
        except ValueError:
            config['encrypted_key']='';self._profile_keys[role]=key
        with self.connection() as db: db.execute('INSERT OR REPLACE INTO role_profiles VALUES(?,?)',(role,json.dumps(config)))
        return self.profiles()
