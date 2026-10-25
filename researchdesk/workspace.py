"""Project settings, content-addressed versions and conflict-aware editing."""
import difflib
import hashlib
import json
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from .catalog import Step, project_steps, resolve_workflow
from .recipes import options_valid
from .store import now


def digest(value):
    if not isinstance(value, bytes): value=json.dumps(value,sort_keys=True,ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()


class Workspace:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store
        self.root=self.store.root/'versions';self.root.mkdir(exist_ok=True)
        (self.root/'blobs').mkdir(exist_ok=True)
        with self.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS project_versions(id TEXT PRIMARY KEY,project_id TEXT,created TEXT,label TEXT,payload TEXT)')
        engine.workspace=self

    def idle(self,pid):
        if pid in self.engine.active or self.engine.assistant and pid in self.engine.assistant.active:
            raise ValueError('项目正在写入，请等任务结束或暂停后再操作')

    def manifest(self,pid,save=False):
        project=self.store.get(pid);files={};total=0
        for entry in self.store.files(pid):
            name=entry['path']
            # Raw evidence and audit history are append-only across restores.
            if name.split('/')[0] in ('audit','materials','references'):continue
            if name=='exports/project.zip':continue
            f=self.store.path(pid,name)
            total+=entry['size']
            if entry['size']>30_000_000 or total>150_000_000:raise ValueError('版本文件超出上限：单个30MB、总计150MB')
            raw=f.read_bytes();sha=digest(raw)
            files[name]={'sha256':sha,'size':len(raw)}
            if save:
                blob=self.root/'blobs'/sha
                if not blob.exists():blob.write_bytes(raw)
        return {'files':files,'project':{k:project.get(k) for k in ('title','goal','template','cursor','status','skip_compute','options','workflow')}}

    def capture(self,pid,label='手动保存',internal=False):
        with self.engine.guard:
            if not internal:self.idle(pid)
            payload=self.manifest(pid,True);vid=uuid.uuid4().hex
            with self.store.connection() as db:
                db.execute('INSERT INTO project_versions VALUES(?,?,?,?,?)',(vid,pid,now(),str(label)[:160],json.dumps(payload,ensure_ascii=False)))
            return {'id':vid,'label':label,'files':len(payload['files'])}

    def list(self,pid):
        self.store.get(pid)
        with self.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT id,created,label FROM project_versions WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,))]

    def version(self,pid,vid):
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM project_versions WHERE id=? AND project_id=?',(vid,pid)).fetchone()
        if not row:raise ValueError('版本不存在')
        return json.loads(row['payload'])

    def preview(self,pid,vid):
        with self.engine.guard:
            self.idle(pid);target=self.version(pid,vid);current=self.manifest(pid)
            changes=[]
            for name in sorted(set(current['files'])|set(target['files'])):
                a=current['files'].get(name);b=target['files'].get(name)
                if a==b:continue
                change={'path':name,'action':'restore' if a and b else 'recover' if b else 'recycle','before':a,'after':b}
                if Path(name).suffix in ('.md','.txt','.py','.json','.csv','.svg','.tex','.html','.css','.js','.bib','.sql') and max((a or {}).get('size',0),(b or {}).get('size',0))<100000:
                    old=self.store.path(pid,name).read_text('utf-8',errors='replace') if a else ''
                    new=(self.root/'blobs'/b['sha256']).read_text('utf-8',errors='replace') if b else ''
                    change['diff']=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='当前/'+name,tofile='目标/'+name))[:18000]
                changes.append(change)
            settings={k:{'before':current['project'].get(k),'after':target['project'].get(k)} for k in ('title','goal','options','cursor','template') if current['project'].get(k)!=target['project'].get(k)}
            return {'version_id':vid,'token':digest({'version':vid,'current':current}),'changes':changes,'settings':settings,
                'notice':'恢复前会保存当前版本。新文件移入回收区；原始资料、参考文献和审计记录保留。待确认任务将取消。'}

    def restore(self,pid,vid,token):
        with self.engine.guard:
            self.idle(pid);preview=self.preview(pid,vid)
            if token!=preview['token']:raise ValueError('预览后项目发生变化，请重新预览再确认')
            target=self.version(pid,vid)
            # Verify every blob before the first mutation.
            for name,entry in target['files'].items():
                self.store.path(pid,name)
                blob=self.root/'blobs'/entry['sha256']
                if not blob.is_file() or digest(blob.read_bytes())!=entry['sha256']:raise ValueError('历史版本内容损坏，未恢复')
            safety=self.capture(pid,'恢复前自动保存')
            before=self.version(pid,safety['id'])
            recycle=self.store.root/'recycle'/pid/uuid.uuid4().hex
            try:
                for change in preview['changes']:
                    dest=self.store.path(pid,change['path'])
                    if change['action']=='recycle':
                        moved=recycle/change['path'];moved.parent.mkdir(parents=True,exist_ok=True);dest.replace(moved)
                    else:
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        temp=dest.with_suffix(dest.suffix+'.tmp');temp.write_bytes((self.root/'blobs'/change['after']['sha256']).read_bytes());temp.replace(dest)
                self._metadata(pid,target['project'])
                with self.store.connection() as db:
                    db.execute("UPDATE chat_turns SET status='cancelled',error='项目已恢复历史版本，请重新提出任务' WHERE project_id=? AND status='proposed'",(pid,))
            except Exception:
                # Restore the safety version without changing its original identity.
                for change in preview['changes']:
                    dest=self.store.path(pid,change['path']);old=before['files'].get(change['path'])
                    if old:
                        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((self.root/'blobs'/old['sha256']).read_bytes())
                    else:dest.unlink(missing_ok=True)
                self._metadata(pid,before['project'])
                raise
            self.store.event(pid,'info','恢复项目历史版本；恢复前快照：'+safety['id'])
            return {'ok':True,'undo_version':safety['id'],'recycled':sum(c['action']=='recycle' for c in preview['changes'])}

    def _metadata(self,pid,meta):
        current=self.store.get(pid);revision=current.get('config_revision',1)+1
        cfg={'options':meta.get('options') or {},'config_revision':revision}
        if meta.get('workflow'):cfg['workflow']=meta['workflow']
        # Restoring a running checkpoint never resumes model or code execution.
        status=meta['status'] if meta['status'] in ('draft','review','awaiting_execution','completed') else 'paused'
        with self.store.connection() as db:
            db.execute('UPDATE projects SET title=?,goal=?,template=?,cursor=?,status=?,skip_compute=?,error=?,updated=? WHERE id=?',
                (meta['title'],meta['goal'],meta['template'],meta['cursor'],status,meta['skip_compute'],'',now(),pid))
            db.execute('INSERT OR REPLACE INTO project_config VALUES(?,?)',(pid,json.dumps(cfg,ensure_ascii=False)))

    def patch_settings(self,pid,patch,revision):
        with self.engine.guard:
            self.idle(pid);p=self.store.get(pid)
            if int(revision)!=p.get('config_revision',1):raise ValueError('项目设置已改变，请刷新后重试')
            if not isinstance(patch,dict) or not patch or set(patch)-{'title','goal','options'}:raise ValueError('项目设置字段无效')
            title=str(patch.get('title',p['title'])).strip();goal=str(patch.get('goal',p['goal'])).strip()
            if not 1<=len(title)<=160 or not 1<=len(goal)<=20000:raise ValueError('项目名称或目标长度无效')
            previous=options_valid(p.get('options',{}))
            if not isinstance(patch.get('options',{}),dict):raise ValueError('项目选项应为对象')
            opts=options_valid({**previous,**patch.get('options',{})})
            structural=('skip_figures','skip_diagrams','max_rounds','enable_review','output_format','stop_after_plan','research_type')
            if p['cursor'] and any(opts.get(k)!=previous.get(k) for k in structural):
                raise ValueError('已开始的流程不能直接改变步骤结构；请先恢复到开始前的版本或新建项目')
            self.capture(pid,'修改项目设置前')
            workflow=resolve_workflow(p['template'],opts,Step) if not p['cursor'] else project_steps(p)
            cfg={'options':opts,'config_revision':p.get('config_revision',1)+1}
            if workflow:cfg['workflow']=[asdict(s) for s in workflow]
            with self.store.connection() as db:
                db.execute('UPDATE projects SET title=?,goal=?,updated=? WHERE id=?',(title,goal,now(),pid))
                db.execute('INSERT OR REPLACE INTO project_config VALUES(?,?)',(pid,json.dumps(cfg,ensure_ascii=False)))
            self.store.event(pid,'info','项目设置已更新，仅用于后续调用')
            return self.store.get(pid)

    def edit(self,pid,path,content,expected_hash):
        from .assistant import editable_path
        with self.engine.guard:
            self.idle(pid);p=self.store.get(pid);f=self.store.path(pid,path)
            if not editable_path(path):raise ValueError('此路径不可编辑')
            if path.startswith('code/') and p['status'] not in ('draft','awaiting_execution'):raise ValueError('代码只可在开始前或等待执行确认时修改')
            actual=digest(f.read_bytes()) if f.exists() else None
            if expected_hash!=actual:raise ValueError('文件已在别处修改，请重新打开后再保存')
            if not isinstance(content,str) or not content.strip():raise ValueError('文件内容不能为空')
            if path.endswith('.py'):compile(content,path,'exec')
            if path.endswith('.svg'):validate_svg(content)
            self.capture(pid,'编辑文件前：'+path)
            self.store.write(pid,path,content)
            self.store.event(pid,'info','用户编辑：'+path)
            return {'ok':True,'sha256':digest(content.encode())}

    def skill(self,name):
        from .recipes import SOURCE_SKILLS
        if name not in SOURCE_SKILLS:raise ValueError('未知步骤指导语')
        custom=self.store.root/'skills'/name/'SKILL.md'
        source=Path(__file__).resolve().parent.parent/'skills'/name/'SKILL.md'
        f=custom if custom.is_file() else source
        if not f.is_file():raise ValueError('指导语文件不存在')
        raw=f.read_bytes()
        return {'name':name,'content':raw.decode('utf-8'),'sha256':digest(raw),'custom':custom.is_file()}

    def save_skill(self,name,content,expected):
        current=self.skill(name)
        if current['sha256']!=expected:raise ValueError('指导语已改变，请重新打开')
        if not isinstance(content,str) or not 1<=len(content.encode())<=100000:raise ValueError('指导语应为1至100000字节')
        folder=self.store.root/'skills'/name;folder.mkdir(parents=True,exist_ok=True)
        path=folder/'SKILL.md'
        if path.exists():
            history=folder/'history';history.mkdir(exist_ok=True);(history/(uuid.uuid4().hex+'.md')).write_bytes(path.read_bytes())
        path.write_text(content,encoding='utf-8',newline='\n')
        return self.skill(name)


def validate_svg(content):
    import xml.etree.ElementTree as ET
    if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper():raise ValueError('SVG 不允许 DTD 或实体')
    try:root=ET.fromstring(content)
    except ET.ParseError:raise ValueError('SVG 不是有效 XML') from None
    if root.tag.split('}')[-1]!='svg':raise ValueError('SVG 根元素错误')
    for node in root.iter():
        if node.tag.split('}')[-1] in ('script','foreignObject','iframe','object','embed','style','animate','set','animateTransform','animateMotion'):raise ValueError('SVG 含不支持的元素')
        for key,value in node.attrib.items():
            key=key.split('}')[-1].lower()
            safe_value=re.sub(r'url\(\s*#[\w-]+\s*\)','',value)
            if key.startswith('on') or key in ('href','src') and not value.startswith('#') or re.search(r'(?:url\s*\(|javascript\s*:|@import)',safe_value,re.I):raise ValueError('SVG 需自包含且不含脚本或外链')
    return root
