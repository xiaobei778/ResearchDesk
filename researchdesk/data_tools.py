import csv
import hashlib
import io
import json
import zipfile
from .store import now


def data_audit(store,pid):
    inputs=[f for f in store.files(pid) if f['path'].startswith('materials/') and f['path'].lower().endswith('.csv')]
    if not inputs:raise ValueError('缺少真实CSV数据。请上传题目数据，或从本机问卷中心导入实际答卷，再重试此步骤。')
    reports=[]
    for entry in inputs[:30]:
        raw=store.path(pid,entry['path']).read_bytes()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:text=raw.decode('gb18030',errors='replace')
        reader=csv.reader(io.StringIO(text));header=next(reader,[])
        if not header:raise ValueError('CSV缺少表头：'+entry['path'])
        if len(header)>1000:raise ValueError('CSV列数超过1000')
        count=0;bad_rows=0;duplicates=0;seen=set();missing=[0]*len(header)
        for row in reader:
            count+=1
            if count>200000:raise ValueError('当前数据检查每文件最多20万行，请先分批处理')
            if len(row)!=len(header):bad_rows+=1
            key=hashlib.sha256(json.dumps(row,ensure_ascii=False).encode()).digest()
            if key in seen:duplicates+=1
            seen.add(key)
            for i in range(len(header)):
                if i>=len(row) or not row[i].strip():missing[i]+=1
        if not count:raise ValueError('CSV只有表头，没有实际数据行：'+entry['path'])
        reports.append({'path':entry['path'],'sha256':hashlib.sha256(raw).hexdigest(),'rows':count,'columns':header,'missing_per_column':missing,'duplicate_rows':duplicates,'malformed_rows':bad_rows,'origin':'uploaded_or_human_entered; not independently verified'})
    report={'created':now(),'files':reports,'notice':'重复和缺失是诊断信息，不自动删行；真实性与样本代表性需人工核验。仅检查实际材料，不生成答卷。'}
    store.write(pid,'docs/data_quality.json',json.dumps(report,ensure_ascii=False,indent=2))
    store.write(pid,'docs/data_quality.md','# 真实数据质量检查\n\n'+report['notice']+'\n\n'+'\n\n'.join(f"## {r['path']}\n\n数据行：{r['rows']}；列数：{len(r['columns'])}；重复行：{r['duplicate_rows']}；列数异常行：{r['malformed_rows']}。\n\n列名："+'、'.join(r['columns']) for r in reports))


def submission(store,pid):
    project=store.get(pid);package=store.path(pid,'exports/submission.zip')
    entries=[f for f in store.files(pid) if f['path'].split('/')[0] in ('paper','code','figures','results') or f['path'] in ('exports/paper.docx','exports/paper.pdf')]
    if not any(f['path'].startswith('code/') for f in entries) or not any(f['path'] in ('exports/paper.docx','exports/paper.pdf') for f in entries):raise ValueError('提交候选包缺少实际代码或导出论文，请先完成对应步骤')
    manifest={'title':project['title'],'created':now(),'files':[{'path':e['path'],'size':e['size'],'sha256':hashlib.sha256(store.path(pid,e['path']).read_bytes()).hexdigest()} for e in entries],
        'notice':'本包为待人工核验的提交候选，不代表官方合规。请核验赛题命名、匿名要求、输出格式、结果文件和AI声明。'}
    store.write(pid,'exports/submission_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for e in entries:z.write(store.path(pid,e['path']),e['path'])
        z.write(store.path(pid,'exports/submission_manifest.json'),'submission_manifest.json')
