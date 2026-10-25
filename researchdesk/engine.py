import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
import shutil
import xml.etree.ElementTree as ET
from .catalog import BY_ID, STEPS, SYSTEM, TEMPLATES, project_steps
from . import providers
from . import demo
from .artifacts import export_paper, figures, validate_metrics
from .store import now
from .data_tools import data_audit, submission

class Engine:
    def __init__(self, store):
        self.store = store
        self.guard = threading.RLock()
        self.active = {}
        self.assistant = None

    def detail(self, pid):
        project = self.store.get(pid)
        project['steps'] = [{'id':s.id,'name':s.name,'review':s.review,'outputs':s.outputs,'kind':s.kind,'skill':s.skill or s.id} for s in project_steps(project)]
        project['files'] = self.store.files(pid)
        project['events'], project['receipts'] = self.store.history(pid)
        with self.guard: project['busy'] = pid in self.active
        if self.assistant: project.update(self.assistant.detail(pid))
        return project

    def start(self, pid, action='continue'):
        with self.guard:
            if pid in self.active: raise ValueError('该项目已有任务在运行')
            if self.assistant and pid in self.assistant.active: raise ValueError('项目助手正在回复，请等待或停止该轮对话')
            p = self.store.get(pid)
            if p['status'] == 'completed' and action != 'export': raise ValueError('项目已经完成，可重新导出成果')
            if action not in ('continue','execute','skip','export'): raise ValueError('未知动作')
            if p['status'] == 'awaiting_execution' and action not in ('execute','skip'): raise ValueError('请先审阅并执行代码，或跳过计算')
            if action in ('execute','skip') and p['status'] != 'awaiting_execution': raise ValueError('当前没有待确认的计算')
            if action == 'export' and p['status'] != 'completed': raise ValueError('请先完成论文流程')
            if p['mode']=='api' and action!='export':
                steps=project_steps(p)
                needed={s.role for s in steps[p['cursor']:] if not s.local}
                if any(not self.store.settings_for_role(role)['model'] for role in needed): raise ValueError('请先配置默认 API 模型或所有所需角色的模型')
            stop = threading.Event()
            self.active[pid] = stop
            self.store.update(pid,status='running',error='')
            thread = threading.Thread(target=self._worker,args=(pid,action,stop),daemon=True)
            thread.start()

    def pause(self, pid):
        with self.guard:
            stop = self.active.get(pid)
            if stop: stop.set()
        self.store.event(pid,'info','已请求暂停；模型调用会在返回后停止，运行中的计算会终止')

    def rerun(self,pid,index):
        with self.guard:
            if pid in self.active or self.assistant and pid in self.assistant.active: raise ValueError('运行中不能重跑')
            project=self.store.get(pid);steps=project_steps(project);index=int(index)
            if not 0<=index<len(steps) or index>project['cursor']: raise ValueError('只能重跑已到达的步骤')
            previous=set(p for s in steps[:index] for p in s.outputs)
            candidates=set(p for s in steps[index:] for p in s.outputs)-previous
            if any(s.id=='code' or s.kind=='code' for s in steps[index:]):
                candidates.update(['results/metrics.json','results/execution.json','results/execution.log','results/metrics.png','results/metrics.svg'])
            stamp=str(time.time_ns())
            for relative in sorted(candidates):
                path=self.store.path(pid,relative)
                if path.is_file():
                    backup=self.store.path(pid,'audit/rerun-'+stamp+'/'+relative)
                    backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup);path.unlink()
            self.store.update(pid,cursor=index,status='paused',error='',skip_compute=0)
            self.store.event(pid,'info','准备重跑：'+steps[index].name+'；后续旧产物已备份到 audit/rerun-'+stamp)
        self.start(pid)

    def _worker(self,pid,action,stop):
        execution_complete=False
        try:
            if action=='export':
                export_paper(self.store,pid)
                self.store.update(pid,status='completed')
                self.store.event(pid,'success','导出已更新')
                return
            if action=='execute':
                self.execute(pid,stop)
                execution_complete=True
            elif action=='skip':
                self.store.path(pid,'results/metrics.json').unlink(missing_ok=True)
                self.store.update(pid,skip_compute=1)
                self.store.write(pid,'results/execution.json',json.dumps({'status':'skipped','notice':'未执行计算，不得生成实验结论'},ensure_ascii=False,indent=2))
                self.store.event(pid,'info','用户跳过计算，后续仅生成方案或基于现有材料写作')
            while True:
                p = self.store.get(pid)
                if stop.is_set():
                    self.store.update(pid,status='paused')
                    return
                steps = project_steps(p)
                if p['cursor'] >= len(steps):
                    self.store.update(pid,status='completed')
                    self.store.event(pid,'success','所有步骤已完成；科研结论仍需人工核验')
                    return
                s = steps[p['cursor']]
                self.store.event(pid,'info','开始：'+s.name)
                if s.local:
                    if s.id=='figures' or s.kind=='figures': figures(self.store,pid)
                    elif s.id=='export' or s.kind=='export': export_paper(self.store,pid)
                    elif s.kind=='data_audit':data_audit(self.store,pid)
                    elif s.kind=='submission':submission(self.store,pid)
                    summary='本地产物已生成'
                else:
                    summary = self.generate(pid,s)
                self.store.receipt(pid,s.id,{'status':'generated','outputs':list(s.outputs),'mode':p['mode']})
                self.store.update(pid,cursor=p['cursor']+1)
                self.store.event(pid,'success',s.name+'：'+summary[:300])
                if s.id=='code' or s.kind=='code':
                    self.store.update(pid,status='awaiting_execution')
                    return
                if s.review:
                    self.store.update(pid,status='review')
                    self.store.event(pid,'review','请审阅 '+', '.join(s.outputs)+' 后继续')
                    return
        except Exception as exc:
            p = self.store.get(pid)
            # A failed execution needs explicit consent again, even after restart.
            if action=='execute' and not execution_complete:
                status='awaiting_execution'
                self.store.path(pid,'results/execution.json').unlink(missing_ok=True)
                metrics=self.store.path(pid,'results/metrics.json')
                if metrics.exists(): metrics.replace(self.store.path(pid,f'audit/failed-metrics-{time.time_ns()}.json'))
            else: status='paused' if stop.is_set() else 'failed'
            message=str(exc)[:1500] or type(exc).__name__
            self.store.update(pid,status=status,error=message)
            self.store.event(pid,'error',message)
        finally:
            if getattr(self,'workspace',None):
                try:self.workspace.capture(pid,'流程停止点自动保存',internal=True)
                except Exception as exc:self.store.event(pid,'error','版本自动保存失败：'+str(exc)[:200])
            with self.guard: self.active.pop(pid,None)

    def context(self,pid):
        parts=[]
        consumed=0
        # Prioritize actual execution evidence over lengthy drafts.
        files=sorted(self.store.files(pid),key=lambda f:(not f['path'].startswith('results/'), f['path']))
        for item in files:
            path=item['path']
            if path.startswith(('audit/','exports/')) or path.endswith(('.png','.pdf','.docx','.svg','.zip')): continue
            if self.store.path(pid,path).suffix not in ('.txt','.md','.csv','.json','.py','.bib'): continue
            text=self.store.path(pid,path).read_text('utf-8',errors='replace')[:12000]
            if consumed+len(text)>70000: continue
            parts.append({'path':path,'text':text,'truncated':item['size']>len(text.encode('utf-8'))})
            consumed+=len(text)
        return parts

    def generate(self,pid,step):
        p=self.store.get(pid)
        if p['mode']=='demo': result=demo.response(step,self.store,pid)
        else:
            settings=self.store.settings_for_role(step.role)
            skill_file=Path(__file__).resolve().parent.parent/'skills'/(step.skill or step.id)/'SKILL.md'
            custom=self.store.root/'skills'/(step.skill or step.id)/'SKILL.md'
            if custom.is_file():skill_file=custom
            if not skill_file.exists(): skill_file=Path(__file__).resolve().parent.parent/'skills'/(step.skill or step.id+'.md')
            instruction=step.instruction+('\n\n步骤指导语：\n'+skill_file.read_text('utf-8')[:20000] if skill_file.is_file() else '')
            prompt=json.dumps({'step':step.id,'title':p['title'],'template':p['template'],'goal':p['goal'],
                'instruction':instruction,'required_outputs':list(step.outputs),
                'options':p.get('options',{}),
                'execution':'跳过计算；仅能写方案' if p['skip_compute'] else '请查看实际执行收据；无收据不得声称已执行',
                'materials':self.context(pid)},ensure_ascii=False)
            if self.assistant:
                raw=self.assistant.model_with_tools(pid,SYSTEM,prompt,step.role,'workflow:'+step.id,self.active.get(pid))
            else:
                raw,usage=providers.call(settings,settings['key'],SYSTEM,prompt,step.role)
                self.store.receipt(pid,'api:'+step.id,usage)
            # Preserve exact responses locally to diagnose invalid output, never treat them as successful artifacts.
            self.store.write(pid,f'audit/{step.id}-{time.time_ns()}.txt',raw)
            candidate=raw.strip()
            if candidate.startswith('```'):
                candidate='\n'.join(candidate.splitlines()[1:-1])
            try: result=json.loads(candidate)
            except json.JSONDecodeError: raise ValueError('模型未返回有效 JSON；原回复已保存 audit，可调整模型/输出上限后重试') from None
        if not isinstance(result,dict) or not isinstance(result.get('files'),list): raise ValueError('模型输出缺少 files 列表')
        entries=result['files']
        paths=[f.get('path') if isinstance(f,dict) else None for f in entries]
        if len(paths)!=len(set(x for x in paths if isinstance(x,str))) or set(paths)!=set(step.outputs):
            raise ValueError('模型产物路径与当前步骤要求不符，请重试；原回复保存在 audit')
        for entry in entries:
            if not isinstance(entry.get('content'),str) or not entry['content'].strip(): raise ValueError('模型返回了空文件')
            if len(entry['content'].encode('utf-8'))>2_000_000: raise ValueError('模型文件过大')
            if entry['path'].endswith('.py'):
                try: compile(entry['content'],entry['path'],'exec')
                except SyntaxError as exc: raise ValueError(f'生成的 Python 存在语法错误：第 {exc.lineno} 行') from None
            if entry['path'].endswith('.svg'):
                try:
                    tree=ET.fromstring(entry['content'])
                    if tree.tag.split('}')[-1]!='svg': raise ValueError('SVG 根元素错误')
                    for node in tree.iter():
                        if node.tag.split('}')[-1] in ('script','foreignObject'): raise ValueError('SVG 含不允许的元素')
                        for key,value in node.attrib.items():
                            if key.split('}')[-1].startswith('on') or key.split('}')[-1]=='href' and not value.startswith('#'): raise ValueError('SVG 必须自包含且不含脚本事件')
                except ET.ParseError: raise ValueError('模型生成的 SVG 不是有效 XML，请重试') from None
        for entry in entries:
            self.store.write(pid,entry['path'],entry['content'])
        return str(result.get('summary','产物已生成'))

    def execute(self,pid,stop):
        project=self.store.get(pid)
        steps=project_steps(project)
        previous=steps[project['cursor']-1] if project['cursor'] else None
        script_path=next((p for p in previous.outputs if p.endswith('.py')),'code/experiment.py') if previous else 'code/experiment.py'
        script=self.store.path(pid,script_path)
        raw=script.read_bytes()
        metrics=self.store.path(pid,'results/metrics.json')
        # Old results never satisfy a new execution.
        if metrics.exists(): metrics.unlink()
        receipt=self.store.path(pid,'results/execution.json')
        if receipt.exists(): receipt.unlink()
        env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','TEMP','TMP','PATH','USERPROFILE','LOCALAPPDATA')}
        env['PYTHONIOENCODING']='utf-8'
        root=script.parent.parent
        started=now()
        log=self.store.path(pid,'results/execution.log')
        with log.open('wb') as output:
            process=subprocess.Popen([sys.executable,'-X','utf8','-I','-B',str(script)],cwd=root,env=env,stdout=output,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+120
            while process.poll() is None:
                if stop.is_set() or time.monotonic()>deadline or log.stat().st_size>10_000_000:
                    self._kill(process)
                    raise ValueError('计算已停止（暂停、120 秒超时或日志超过 10 MB），请检查代码后重新确认执行')
                time.sleep(.1)
        if process.returncode!=0: raise ValueError(f'计算退出码 {process.returncode}；请查看 results/execution.log 并修正代码')
        if not metrics.exists() or metrics.stat().st_size>1_000_000: raise ValueError('计算没有生成有效大小的 results/metrics.json')
        try: data=validate_metrics(json.loads(metrics.read_text('utf-8')))
        except (ValueError,TypeError) as exc:
            metrics.unlink(missing_ok=True)
            raise ValueError('计算结果格式不符合契约：'+str(exc)) from None
        if project['template'] in ('survey_market','comp_mathorcup_bigdata') and data['dataset_origin']!='uploaded':
            metrics.unlink(missing_ok=True)
            raise ValueError('此项目要求使用实际上传数据，不能用仿真结果替代')
        payload={'status':'executed','started':started,'finished':now(),'exit_code':process.returncode,
                 'code_sha256':hashlib.sha256(raw).hexdigest(),'metrics_sha256':hashlib.sha256(metrics.read_bytes()).hexdigest(),
                 'dataset_origin':data['dataset_origin'],'input_files':[{'path':f['path'],'sha256':hashlib.sha256(self.store.path(pid,f['path']).read_bytes()).hexdigest()} for f in self.store.files(pid) if f['path'].startswith('materials/')],
                 'notice':'仅验证执行与产物；输入哈希记录文件身份，不证明数据真实性或科研有效性'}
        self.store.write(pid,'results/execution.json',json.dumps(payload,ensure_ascii=False,indent=2))
        self.store.receipt(pid,'execution',payload)
        self.store.event(pid,'success','代码实际执行成功，指标与哈希收据已保存')

    @staticmethod
    def _kill(process):
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else: process.kill()
        process.wait(timeout=10)
