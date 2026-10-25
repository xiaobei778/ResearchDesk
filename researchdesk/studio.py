"""Editable SVG diagrams and local questionnaires backed by real responses."""
import csv
import html
import io
import json
import math
import re
import uuid
from .store import now
from .workspace import digest


class Studio:
    def __init__(self,app):
        self.app=app;self.store=app.store
        with self.store.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS surveys(id TEXT PRIMARY KEY,created TEXT,payload TEXT,revision INTEGER);
            CREATE TABLE IF NOT EXISTS survey_answers(id TEXT PRIMARY KEY,survey_id TEXT,created TEXT,payload TEXT);''')

    def diagrams(self):
        result=[]
        for p in self.store.list():
            for f in self.store.files(p['id']):
                if f['path'].endswith('.diagram.json'):
                    result.append({'project_id':p['id'],'project_title':p['title'],'path':f['path']})
        return result

    def diagram(self,pid,name):
        if not isinstance(name,str) or not re.fullmatch(r'[\w\-\u4e00-\u9fff]{1,60}',name):raise ValueError('图名只能含文字、数字、下划线和短横线')
        path='figures/'+name+'.diagram.json';f=self.store.path(pid,path);svg=self.store.path(pid,'figures/'+name+'.svg')
        token=digest({'json':digest(f.read_bytes()) if f.exists() else None,'svg':digest(svg.read_bytes()) if svg.exists() else None})
        return {'path':path,'name':name,'document':json.loads(f.read_text('utf-8')) if f.exists() else {'width':1000,'height':650,'nodes':[],'edges':[]},'token':token}

    @staticmethod
    def render(document):
        if not isinstance(document,dict):raise ValueError('图数据格式错误')
        def number(x,low,high):
            x=float(x)
            if not math.isfinite(x) or not low<=x<=high:raise ValueError('图形参数超出范围')
            return round(x,2)
        w=number(document.get('width',1000),200,5000);h=number(document.get('height',650),200,5000)
        nodes=document.get('nodes');edges=document.get('edges')
        if not isinstance(nodes,list) or len(nodes)>150 or not isinstance(edges,list) or len(edges)>300:raise ValueError('图形数量超出限制')
        norm=[];ids=set()
        for n in nodes:
            if not isinstance(n,dict):raise ValueError('节点无效')
            nid=n.get('id');text=n.get('text','');fill=n.get('fill','#eef2ff')
            if not isinstance(nid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}',nid) or nid in ids:raise ValueError('节点ID重复或无效')
            if not isinstance(text,str) or len(text)>500 or not re.fullmatch(r'#[a-fA-F0-9]{6}',fill):raise ValueError('文字或颜色无效')
            a={'id':nid,'x':number(n.get('x',20),0,w),'y':number(n.get('y',20),0,h),'w':number(n.get('w',180),30,w),'h':number(n.get('h',80),24,h),'text':text,'fill':fill,'shape':'ellipse' if n.get('shape')=='ellipse' else 'rect'}
            if a['x']+a['w']>w or a['y']+a['h']>h:raise ValueError('节点超出画布，请先扩大画布')
            ids.add(nid);norm.append(a)
        byid={n['id']:n for n in norm};lines=[];valid_edges=[]
        for e in edges:
            if not isinstance(e,dict) or e.get('from') not in ids or e.get('to') not in ids or e['from']==e['to']:raise ValueError('连线端点无效')
            a,b=byid[e['from']],byid[e['to']];label=str(e.get('text',''))[:120]
            x1=a['x']+a['w']/2;y1=a['y']+a['h']/2;x2=b['x']+b['w']/2;y2=b['y']+b['h']/2
            dx=x2-x1;dy=y2-y1
            def intersection(n,dx,dy):
                scale=1/max(abs(dx)/(n['w']/2) if dx else 0,abs(dy)/(n['h']/2) if dy else 0,0.0001)
                return (n['x']+n['w']/2+dx*scale,n['y']+n['h']/2+dy*scale)
            sx,sy=intersection(a,dx,dy);tx,ty=intersection(b,-dx,-dy)
            lines.append(f'<path d="M {sx} {sy} L {tx} {ty}" stroke="#64748b" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
            if label:lines.append(f'<text x="{(sx+tx)/2}" y="{(sy+ty)/2-8}" text-anchor="middle" font-size="14">{html.escape(label)}</text>')
            valid_edges.append({'from':e['from'],'to':e['to'],'text':label})
        for n in norm:
            if n['shape']=='ellipse':shape=f'<ellipse cx="{n["x"]+n["w"]/2}" cy="{n["y"]+n["h"]/2}" rx="{n["w"]/2}" ry="{n["h"]/2}"'
            else:shape=f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" rx="12"'
            lines.append(f'<g data-node="{n["id"]}">{shape} fill="{n["fill"]}" stroke="#6366f1" stroke-width="1.6"/>')
            textlines=n['text'].split('\n')[:12]
            for i,line in enumerate(textlines):lines.append(f'<text x="{n["x"]+n["w"]/2}" y="{n["y"]+n["h"]/2+(i-(len(textlines)-1)/2)*21+5}" text-anchor="middle" font-family="Arial, Microsoft YaHei, sans-serif" font-size="16" fill="#1e293b">{html.escape(line)}</text>')
            lines.append('</g>')
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10" fill="#64748b"/></marker></defs><rect width="100%" height="100%" fill="white"/>'+''.join(lines)+'</svg>'
        return {'width':w,'height':h,'nodes':norm,'edges':valid_edges},svg

    def save_diagram(self,pid,name,document,token):
        with self.app.engine.guard:
            self.app.workspace.idle(pid);current=self.diagram(pid,name)
            if token!=current['token']:raise ValueError('这张图已在别处修改，请重新打开')
            normalized,svg=self.render(document);self.app.workspace.capture(pid,'保存流程图前：'+name)
            json_path=current['path'];svg_path='figures/'+name+'.svg'
            old={p:self.store.path(pid,p).read_bytes() if self.store.path(pid,p).exists() else None for p in (json_path,svg_path)}
            try:
                self.store.write(pid,json_path,json.dumps(normalized,ensure_ascii=False,indent=2));self.store.write(pid,svg_path,svg)
            except Exception:
                for p,b in old.items():
                    if b is None:self.store.path(pid,p).unlink(missing_ok=True)
                    else:self.store.path(pid,p).write_bytes(b)
                raise
            return self.diagram(pid,name)

    def survey_list(self):
        with self.store.connection() as db:rows=db.execute('SELECT s.*,COUNT(a.id) AS answers FROM surveys s LEFT JOIN survey_answers a ON s.id=a.survey_id GROUP BY s.id ORDER BY s.created DESC').fetchall()
        return [{**json.loads(r['payload']),'id':r['id'],'revision':r['revision'],'answers':r['answers']} for r in rows]

    def survey_get(self,sid):
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM surveys WHERE id=?',(sid,)).fetchone()
            answers=[dict(r) for r in db.execute('SELECT id,created,payload FROM survey_answers WHERE survey_id=? ORDER BY rowid',(sid,))]
        if not row:raise ValueError('问卷不存在')
        return {**json.loads(row['payload']),'id':sid,'revision':row['revision'],'responses':[{'id':r['id'],'created':r['created'],'answers':json.loads(r['payload'])} for r in answers]}

    def survey_create(self,value):
        title=str(value.get('title','')).strip();questions=value.get('questions')
        if not 1<=len(title)<=160 or not isinstance(questions,list) or not 1<=len(questions)<=60:raise ValueError('请填写问卷标题及1至60个问题')
        result=[]
        for i,q in enumerate(questions):
            if not isinstance(q,dict):raise ValueError('问题格式无效')
            text=str(q.get('text','')).strip();kind=q.get('type','text')
            if not 1<=len(text)<=1000 or kind not in ('text','single','number'):raise ValueError('问题文字或类型无效')
            choices=q.get('choices',[])
            if kind=='single' and (not isinstance(choices,list) or not 2<=len(choices)<=20 or any(not isinstance(x,str) or not x.strip() or len(x)>200 for x in choices) or len(set(choices))!=len(choices)):raise ValueError('单选题需要2至20个不重复选项')
            result.append({'id':'q'+str(i+1),'text':text,'type':kind,'required':bool(q.get('required',True)),'choices':choices if kind=='single' else []})
        sid=uuid.uuid4().hex;data={'title':title,'questions':result,'open':True,'notice':'本机收集的真实答卷；不提供合成数据，不计互助积分'}
        with self.store.connection() as db:db.execute('INSERT INTO surveys VALUES(?,?,?,1)',(sid,now(),json.dumps(data,ensure_ascii=False)))
        return self.survey_get(sid)

    def answer(self,sid,answers):
        if not isinstance(answers,dict):raise ValueError('答卷格式无效')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM surveys WHERE id=?',(sid,)).fetchone()
            if not row:raise ValueError('问卷不存在')
            survey=json.loads(row[0])
            if not survey['open']:raise ValueError('问卷已停止收集')
            if set(answers)-{q['id'] for q in survey['questions']}:raise ValueError('答卷含未知题目')
            normalized={}
            for q in survey['questions']:
                value=answers.get(q['id'],'')
                if value=='' or value is None:
                    if q['required']:raise ValueError('必答题未填写：'+q['text'])
                    normalized[q['id']]='';continue
                if q['type']=='single' and value not in q['choices']:raise ValueError('选项无效')
                if q['type']=='number':
                    value=float(value)
                    if not math.isfinite(value):raise ValueError('数值无效')
                else:
                    if not isinstance(value,str) or len(value)>5000:raise ValueError('答案内容无效')
                normalized[q['id']]=value
            aid=uuid.uuid4().hex
            db.execute('INSERT INTO survey_answers VALUES(?,?,?,?)',(aid,sid,now(),json.dumps(normalized,ensure_ascii=False)))
        return {'ok':True,'response_id':aid}

    def survey_toggle(self,sid,revision):
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM surveys WHERE id=?',(sid,)).fetchone()
            if not row or row['revision']!=revision:raise ValueError('问卷已改变，请刷新')
            data=json.loads(row['payload']);data['open']=not data['open'];db.execute('UPDATE surveys SET payload=?,revision=revision+1 WHERE id=?',(json.dumps(data,ensure_ascii=False),sid))
        return self.survey_get(sid)

    def survey_csv(self,sid):
        survey=self.survey_get(sid);output=io.StringIO();writer=csv.writer(output)
        def safe(value):
            value=str(value)
            return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
        writer.writerow(['response_id','created']+[safe(q['text']) for q in survey['questions']])
        for r in survey['responses']:writer.writerow([r['id'],r['created']]+[safe(r['answers'].get(q['id'],'')) for q in survey['questions']])
        return ('\ufeff'+output.getvalue()).encode('utf-8')

    def survey_import(self,sid,pid):
        with self.app.engine.guard:
            self.app.workspace.idle(pid)
            survey=self.survey_get(sid)
            if not survey['responses']:raise ValueError('没有真实答卷，不能导入空调查数据')
            path='materials/survey-'+sid+'.csv'
            dest=self.store.path(pid,path)
            raw=self.survey_csv(sid)
            # Imported copies stay immutable so references to older data remain meaningful.
            if dest.exists():
                if dest.read_bytes()==raw:return {'ok':True,'path':path,'duplicate':True}
                path='materials/survey-'+sid+'-'+uuid.uuid4().hex[:8]+'.csv'
            self.app.workspace.capture(pid,'导入真实问卷答卷前')
            dest=self.store.path(pid,path);dest.write_bytes(raw)
            self.store.write(pid,path+'.source.json',json.dumps({'survey_id':sid,'title':survey['title'],'responses':len(survey['responses']),'sha256':digest(raw),'imported':now(),'origin':'local_human_entered'},ensure_ascii=False,indent=2))
            self.store.event(pid,'info','已导入真实问卷答卷；已完成的分析需按需要重跑：'+path)
            return {'ok':True,'path':path,'duplicate':False}
