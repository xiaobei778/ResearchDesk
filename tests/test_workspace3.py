import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from researchdesk.server import Application
from researchdesk.workspace import digest


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name);self.store=self.app.store
        self.pid=self.store.create('版本测试','full_pipeline','真实研究目标','api')['id']
    def tearDown(self):self.tmp.cleanup()
    def wait_intake(self,iid):
        deadline=time.monotonic()+6
        while self.app.intake.get(iid)['busy'] and time.monotonic()<deadline:time.sleep(.02)
        self.assertFalse(self.app.intake.get(iid)['busy'])
        return self.app.intake.get(iid)
    def test_version_preview_restore_undo_and_preserve_evidence(self):
        self.store.write(self.pid,'paper/main.md','# 原稿\n')
        self.store.write(self.pid,'materials/raw.csv','x\n1\n')
        version=self.app.workspace.capture(self.pid,'初稿')
        self.store.write(self.pid,'paper/main.md','# 修改稿\n');self.store.write(self.pid,'docs/later.md','后产生')
        preview=self.app.workspace.preview(self.pid,version['id'])
        self.assertEqual({x['action'] for x in preview['changes']},{'restore','recycle'})
        self.assertIn('-# 修改稿',next(x['diff'] for x in preview['changes'] if x['path']=='paper/main.md'))
        result=self.app.workspace.restore(self.pid,version['id'],preview['token'])
        self.assertEqual(self.store.path(self.pid,'paper/main.md').read_text('utf-8'),'# 原稿\n')
        self.assertFalse(self.store.path(self.pid,'docs/later.md').exists())
        self.assertTrue(self.store.path(self.pid,'materials/raw.csv').exists())
        self.assertTrue(any((Path(self.tmp.name)/'recycle').rglob('later.md')))
        undo=self.app.workspace.preview(self.pid,result['undo_version']);self.app.workspace.restore(self.pid,result['undo_version'],undo['token'])
        self.assertEqual(self.store.path(self.pid,'paper/main.md').read_text('utf-8'),'# 修改稿\n')
        self.assertTrue(self.store.path(self.pid,'docs/later.md').exists())
    def test_preview_conflict_and_busy_restore_do_not_write(self):
        self.store.write(self.pid,'paper/main.md','A');version=self.app.workspace.capture(self.pid)
        self.store.write(self.pid,'paper/main.md','B');preview=self.app.workspace.preview(self.pid,version['id'])
        self.store.write(self.pid,'paper/main.md','C')
        with self.assertRaisesRegex(ValueError,'发生变化'):self.app.workspace.restore(self.pid,version['id'],preview['token'])
        self.assertEqual(self.store.path(self.pid,'paper/main.md').read_text('utf-8'),'C')
        self.app.engine.active[self.pid]=threading.Event()
        with self.assertRaisesRegex(ValueError,'正在写入'):self.app.workspace.preview(self.pid,version['id'])
        self.app.engine.active.clear()
    def test_corrupt_history_blob_does_not_change_current_files(self):
        self.store.write(self.pid,'paper/main.md','A');version=self.app.workspace.capture(self.pid)
        self.store.write(self.pid,'paper/main.md','B');preview=self.app.workspace.preview(self.pid,version['id'])
        (self.app.workspace.root/'blobs'/digest(b'A')).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'损坏'):self.app.workspace.restore(self.pid,version['id'],preview['token'])
        self.assertEqual(self.store.path(self.pid,'paper/main.md').read_text('utf-8'),'B')
    def test_settings_revision_freezes_started_workflow(self):
        p=self.app.workspace.patch_settings(self.pid,{'options':{'research_type':'qualitative','degree_level':'master'},'title':'新标题'},1)
        self.assertEqual(p['config_revision'],2)
        with self.assertRaisesRegex(ValueError,'已改变'):self.app.workspace.patch_settings(self.pid,{'title':'旧提案'},1)
        self.store.update(self.pid,cursor=1,status='paused')
        with self.assertRaisesRegex(ValueError,'步骤结构'):self.app.workspace.patch_settings(self.pid,{'options':{'output_format':'docx'}},2)
        p=self.app.workspace.patch_settings(self.pid,{'options':{'requirements':'新要求'}},2)
        self.assertEqual(p['options']['requirements'],'新要求')
    def test_file_edit_conflict_requires_current_hash(self):
        self.store.write(self.pid,'paper/main.md','A')
        self.app.workspace.edit(self.pid,'paper/main.md','B',digest(b'A'))
        with self.assertRaisesRegex(ValueError,'别处修改'):self.app.workspace.edit(self.pid,'paper/main.md','C',digest(b'A'))
        self.assertEqual(self.store.path(self.pid,'paper/main.md').read_text('utf-8'),'B')
    def test_intake_materials_confirmation_is_idempotent_and_never_runs(self):
        import base64
        intake=self.app.intake.new();iid=intake['id'];turn=uuid.uuid4().hex
        self.app.intake.upload(iid,{'name':'题目.md','content':base64.b64encode('国赛题目与约束'.encode()).decode()})
        self.app.intake.send(iid,'帮我做国赛建模',turn,local=True)
        data=self.wait_intake(iid);self.assertEqual(data['status'],'proposed')
        self.assertEqual(len(self.store.list()),1)
        duplicate=self.app.intake.send(iid,'帮我做国赛建模',turn,local=True);self.assertTrue(duplicate['duplicate'])
        result=self.app.intake.confirm(iid,data['revision']);pid=result['project_id']
        self.assertEqual(self.store.get(pid)['status'],'draft')
        self.assertEqual(self.store.path(pid,'materials/题目.md').read_text('utf-8'),'国赛题目与约束')
        self.assertTrue(self.app.intake.confirm(iid,data['revision'])['duplicate'])
        self.assertEqual(len(self.store.list()),2)
    def test_intake_model_call_uses_only_configured_provider(self):
        self.store.save_settings({'model':'fake'})
        data=self.app.intake.new();iid=data['id'];turn=uuid.uuid4().hex
        with patch('researchdesk.providers.call',return_value=(json.dumps({'reply':'缺研究方向，请补充','proposal':None}),{})) as call:
            self.app.intake.send(iid,'我想写论文',turn);data=self.wait_intake(iid)
            self.assertEqual(call.call_count,1);self.assertEqual(data['status'],'draft')
        self.assertEqual(len(self.store.list()),1)
    def test_settings_proposal_waits_for_confirmation(self):
        self.store.save_settings({'model':'fake'})
        proposal={'type':'project_settings','title':'更新标题','patch':{'title':'对话修改的标题'}}
        turn=uuid.uuid4().hex
        with patch('researchdesk.providers.call',return_value=(json.dumps({'reply':'请确认','proposal':proposal}),{})):
            self.app.assistant.send(self.pid,'标题改一下','auto',turn)
            deadline=time.monotonic()+6
            while self.pid in self.app.assistant.active and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(self.store.get(self.pid)['title'],'版本测试')
        self.app.assistant.operate(self.pid,turn,'approve',1)
        self.assertEqual(self.store.get(self.pid)['title'],'对话修改的标题')
    def test_diagram_roundtrip_conflict_and_escaped_text(self):
        diagram=self.app.studio.diagram(self.pid,'技术路线')
        doc={'width':1000,'height':650,'nodes':[{'id':'a','x':10,'y':20,'text':'<script> & 方法'},{'id':'b','x':300,'y':200,'text':'结果'}],'edges':[{'from':'a','to':'b'}]}
        saved=self.app.studio.save_diagram(self.pid,'技术路线',doc,diagram['token'])
        svg=self.store.path(self.pid,'figures/技术路线.svg').read_text('utf-8')
        self.assertIn('&lt;script&gt;',svg);self.assertIn('marker-end',svg)
        with self.assertRaisesRegex(ValueError,'别处修改'):self.app.studio.save_diagram(self.pid,'技术路线',doc,diagram['token'])
        doc['edges'][0]['to']='missing'
        with self.assertRaisesRegex(ValueError,'端点'):self.app.studio.save_diagram(self.pid,'技术路线',doc,saved['token'])
    def test_survey_real_answers_validation_close_and_csv(self):
        survey=self.app.studio.survey_create({'title':'真实调查','questions':[{'text':'选项','type':'single','choices':['甲','乙']},{'text':'数值','type':'number'}]})
        with self.assertRaises(ValueError):self.app.studio.answer(survey['id'],{'q1':'虚构选项','q2':1})
        self.assertEqual(len(self.app.studio.survey_get(survey['id'])['responses']),0)
        self.app.studio.answer(survey['id'],{'q1':'甲','q2':1.5})
        self.assertIn('甲',self.app.studio.survey_csv(survey['id']).decode('utf-8'))
        self.app.studio.survey_toggle(survey['id'],1)
        with self.assertRaisesRegex(ValueError,'停止收集'):self.app.studio.answer(survey['id'],{'q1':'甲','q2':2})

    def test_survey_import_preserves_actual_answers_and_has_repeat_receipt(self):
        from researchdesk.data_tools import data_audit
        survey=self.app.studio.survey_create({'title':'测试真实数据','questions':[{'text':'实际数值','type':'number'}]})
        with self.assertRaisesRegex(ValueError,'没有真实答卷'):self.app.studio.survey_import(survey['id'],self.pid)
        self.app.studio.answer(survey['id'],{'q1':2.5})
        imported=self.app.studio.survey_import(survey['id'],self.pid)
        self.assertIn('2.5',self.store.path(self.pid,imported['path']).read_text('utf-8'))
        self.assertTrue(self.app.studio.survey_import(survey['id'],self.pid)['duplicate'])
        data_audit(self.store,self.pid)
        report=json.loads(self.store.path(self.pid,'docs/data_quality.json').read_text('utf-8'))
        self.assertEqual(report['files'][0]['rows'],1)

    def test_custom_instruction_is_used_and_conflict_protected(self):
        from researchdesk.catalog import project_steps
        self.store.save_settings({'model':'fake'})
        original=self.app.workspace.skill('research-lit')
        self.app.workspace.save_skill('research-lit','本机自有指令：逐条说明证据缺口',original['sha256'])
        with self.assertRaisesRegex(ValueError,'已改变'):self.app.workspace.save_skill('research-lit','旧覆盖',original['sha256'])
        step=next(s for s in project_steps(self.store.get(self.pid)) if s.skill=='research-lit')
        reply=json.dumps({'files':[{'path':p,'content':'完整产物'} for p in step.outputs]})
        with patch('researchdesk.providers.call',return_value=(reply,{})) as call:
            self.app.engine.generate(self.pid,step)
            self.assertIn('本机自有指令',json.loads(call.call_args.args[3])['instruction'])

    def test_bigdata_workflow_runs_uploaded_csv_and_builds_real_submission(self):
        from researchdesk.catalog import project_steps
        from researchdesk import demo
        self.store.save_settings({'model':'fake'})
        pid=self.store.create('大数据全链验收','comp_mathorcup_bigdata','对实际CSV数据统计均值','api',{'output_format':'docx','skip_diagrams':True})['id']
        self.store.write(pid,'materials/values.csv','value\n2\n4\n6\n')
        code='''import csv,json,pathlib
p=pathlib.Path('.')
with (p/'materials/values.csv').open(encoding='utf-8') as f:values=[float(r['value']) for r in csv.DictReader(f)]
(p/'results/metrics.json').write_text(json.dumps({'metrics':[{'name':'mean','value':sum(values)/len(values),'unit':''}],'dataset_origin':'uploaded','method':'CSV arithmetic mean','notes':[]}),encoding='utf-8')
'''
        def model(settings,key,system,prompt,role):
            task=json.loads(prompt)
            return json.dumps({'summary':'本地假模型','files':[{'path':p,'content':code if p.endswith('.py') else '# 数据分析草稿\n\n依据实际计算收据进行人工核验。'} for p in task['required_outputs']]}),{}
        with patch('researchdesk.providers.call',side_effect=model):
            for _ in range(12):
                p=self.store.get(pid)
                if p['status']=='completed':break
                self.app.engine.start(pid,'execute' if p['status']=='awaiting_execution' else 'continue')
                deadline=time.monotonic()+8
                while pid in self.app.engine.active and time.monotonic()<deadline:time.sleep(.02)
                self.assertNotEqual(self.store.get(pid)['status'],'failed',self.store.get(pid)['error'])
        self.assertEqual(self.store.get(pid)['status'],'completed')
        self.assertEqual(json.loads(self.store.path(pid,'results/metrics.json').read_text('utf-8'))['metrics'][0]['value'],4)
        import zipfile
        with zipfile.ZipFile(self.store.path(pid,'exports/submission.zip')) as z:
            self.assertIn('exports/paper.docx',z.namelist());self.assertIn('code/experiment.py',z.namelist());self.assertIn('submission_manifest.json',z.namelist())


if __name__=='__main__':unittest.main()
