import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from researchdesk.assistant import Assistant
from researchdesk.catalog import TEMPLATES, Step, project_steps
from researchdesk.engine import Engine
from researchdesk.recipes import SOURCE_SKILLS
from researchdesk.store import Store

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.engine=Engine(self.store);self.agent=Assistant(self.engine)
    def tearDown(self): self.tmp.cleanup()
    def pid(self,mode='demo',template='research',options=None): return self.store.create('新版测试',template,'研究目标与约束',mode,options)['id']
    def wait(self,pid):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if pid not in self.agent.active and pid not in self.engine.active: return self.engine.detail(pid)
            time.sleep(.025)
        self.fail('task timeout')
    def send(self,pid,text='帮我整理研究计划',mode='focused',turn=None):
        turn=turn or uuid.uuid4().hex
        self.agent.send(pid,text,mode,turn);p=self.wait(pid)
        return p,next(x for x in p['messages'] if x['turn_id']==turn)
    def test_catalog_has_40_distinct_recipes_and_51_skills(self):
        templates={k:v for k,v in TEMPLATES.items() if not v.get('legacy')}
        self.assertEqual(len(templates),40);self.assertEqual(len(SOURCE_SKILLS),51)
        for key in templates:
            p=self.store.create('合同测试',key,'测试目标','api')
            steps=project_steps(p)
            self.assertTrue(steps)
            for step in steps:
                self.assertTrue(step.outputs)
                for path in step.outputs: self.store.path(p['id'],path)
        self.assertNotEqual(TEMPLATES['comp_mcm']['steps'],TEMPLATES['literature_review']['steps'])
    def test_parameterized_workflow_is_frozen_after_restart(self):
        pid=self.pid('api','comp_cumcm',{'skip_figures':True,'skip_diagrams':True,'enable_review':False,'output_format':'docx'})
        p=self.store.get(pid);steps=project_steps(p)
        self.assertFalse(any(s.kind=='figures' or s.skill in ('comp-review','paper-figure-drawio') for s in steps))
        self.assertEqual(steps[-1].outputs,('exports/paper.docx',))
        self.assertEqual(project_steps(Store(self.tmp.name).get(pid)),steps)
    def test_demo_proposal_edit_apply_idempotency_and_rollback(self):
        pid=self.pid();p,turn=self.send(pid)
        self.assertEqual(turn['status'],'proposed');self.assertFalse(self.store.path(pid,'docs/next_plan.md').exists())
        edited=turn['response']['proposal'];edited['files'][0]['content']='# 用户编辑过的计划\n\n多行内容\n'
        self.agent.operate(pid,turn['turn_id'],'edit',1,edited)
        with self.assertRaisesRegex(ValueError,'版本'):self.agent.operate(pid,turn['turn_id'],'approve',1)
        self.agent.operate(pid,turn['turn_id'],'approve',2)
        self.assertEqual(self.store.path(pid,'docs/next_plan.md').read_text('utf-8'),'# 用户编辑过的计划\n\n多行内容\n')
        self.assertTrue(self.agent.operate(pid,turn['turn_id'],'approve',2)['duplicate'])
        snapshot=self.agent.detail(pid)['snapshots'][0]
        self.agent.rollback(pid,snapshot['id'])
        self.assertFalse(self.store.path(pid,'docs/next_plan.md').exists())
    def test_conversation_mode_cannot_modify_files(self):
        pid=self.pid();p,turn=self.send(pid,mode='conversation')
        self.assertIsNone(turn['response']['proposal'])
        self.assertFalse(self.store.path(pid,'docs/next_plan.md').exists())
    def test_duplicate_turn_never_calls_model_twice(self):
        pid=self.pid('api');self.store.save_settings({'model':'fake'})
        result=json.dumps({'reply':'已处理','proposal':None})
        turn=uuid.uuid4().hex
        with patch('researchdesk.providers.call',return_value=(result,{})) as call:
            self.send(pid,text='解释当前方案',mode='conversation',turn=turn)
            duplicate=self.agent.send(pid,'解释当前方案','conversation',turn)
            self.assertTrue(duplicate['duplicate']);self.assertEqual(call.call_count,1)
    def test_actual_tool_loop_reads_project_then_replies(self):
        pid=self.pid('api');self.store.save_settings({'model':'fake'});self.store.write(pid,'docs/input.md','真实材料内容')
        responses=[(json.dumps({'tool':{'name':'read_file','arguments':{'path':'docs/input.md'}}}),{}),(json.dumps({'reply':'基于材料回答','proposal':None}),{})]
        with patch('researchdesk.providers.call',side_effect=responses) as call:
            p,turn=self.send(pid,text='读取资料后解释',mode='conversation')
            self.assertEqual(turn['status'],'done')
            second=json.loads(call.call_args_list[1].args[3])
            self.assertEqual(second['_tool_results'][0]['result']['content'],'真实材料内容')
        self.assertTrue(any(e['kind']=='tool' for e in p['events']))
    def test_stop_confirmation_and_restart_do_not_apply_proposals(self):
        pid=self.pid('api');self.store.save_settings({'model':'fake'})
        entered=threading.Event();release=threading.Event()
        def slow(*args):
            entered.set();release.wait(4);return json.dumps({'reply':'返回','proposal':None}),{}
        with patch('researchdesk.providers.call',side_effect=slow):
            self.agent.send(pid,'停止测试','auto',uuid.uuid4().hex);self.assertTrue(entered.wait(3))
            status=self.agent.stop(pid);self.assertFalse(status['stopped']);release.set();p=self.wait(pid)
            self.assertEqual(p['messages'][-1]['status'],'cancelled')
        with self.store.connection() as db: db.execute("UPDATE chat_turns SET status='running' WHERE project_id=?",(pid,))
        recovered=Store(self.tmp.name)
        with recovered.connection() as db:self.assertEqual(db.execute('SELECT status FROM chat_turns WHERE project_id=?',(pid,)).fetchone()[0],'interrupted')
    def test_proposal_conflict_and_rollback_protect_later_edits(self):
        pid=self.pid();p,turn=self.send(pid)
        self.store.write(pid,'docs/next_plan.md','后来的编辑')
        with self.assertRaisesRegex(ValueError,'已改变'):self.agent.operate(pid,turn['turn_id'],'approve',1)
        edited=turn['response']['proposal'];self.agent.operate(pid,turn['turn_id'],'edit',1,edited)
        self.agent.operate(pid,turn['turn_id'],'approve',2)
        self.store.write(pid,'docs/next_plan.md','再次修改')
        snapshot=self.agent.detail(pid)['snapshots'][0]
        with self.assertRaisesRegex(ValueError,'无法安全回滚'):self.agent.rollback(pid,snapshot['id'])
        self.assertEqual(self.store.path(pid,'docs/next_plan.md').read_text('utf-8'),'再次修改')
    def test_unsafe_proposals_are_rejected(self):
        pid=self.pid()
        for path in ('../evil.py','results/metrics.json','results/execution.json','audit/proof.md','materials/original.md'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                self.agent.validate_proposal(pid,{'type':'write_files','title':'test','files':[{'path':path,'content':'bad'}]})

    def test_generated_svg_is_validated_before_writing(self):
        pid=self.pid('api');self.store.save_settings({'model':'fake'})
        step=Step('svg-check','SVG','writer',('figures/method.svg',),'SVG')
        invalid=['<svg><g></svg>','<html/>',
            '<svg><script>alert(1)</script></svg>',
            '<svg><foreignObject/></svg>',
            '<svg onload="alert(1)"/>',
            '<svg><image href="https://example.invalid/image.png"/></svg>']
        for svg in invalid:
            response=json.dumps({'files':[{'path':step.outputs[0],'content':svg}]})
            with self.subTest(svg=svg),patch('researchdesk.providers.call',return_value=(response,{})),self.assertRaises(ValueError):
                self.engine.generate(pid,step)
            self.assertFalse(self.store.path(pid,step.outputs[0]).exists())
        valid='<svg xmlns="http://www.w3.org/2000/svg"><text x="5" y="10">方法</text></svg>'
        with patch('researchdesk.providers.call',return_value=(json.dumps({'files':[{'path':step.outputs[0],'content':valid}]}),{})):
            self.engine.generate(pid,step)
        self.assertEqual(self.store.path(pid,step.outputs[0]).read_text('utf-8'),valid)
    def test_independent_role_credentials_are_separate_and_redacted(self):
        self.store.save_settings({'model':'default','api_key':'default-secret'})
        self.store.save_profile({'role':'reviewer','model':'reviewer','endpoint':'http://127.0.0.1:9999/v1','protocol':'anthropic','api_key':'reviewer-secret'})
        self.assertEqual(self.store.settings_for_role('reviewer')['key'],'reviewer-secret')
        self.assertEqual(self.store.settings_for_role('writer')['key'],'default-secret')
        self.assertNotIn('reviewer-secret',json.dumps(self.store.profiles()))
        self.store.save_profile({'role':'reviewer','inherit':True})
        self.assertEqual(self.store.settings_for_role('reviewer')['model'],'default')
    def test_rerun_invalidates_old_metrics_and_old_execution_receipt(self):
        pid=self.pid();self.store.update(pid,cursor=12,status='completed')
        self.store.write(pid,'results/metrics.json','{"old":true}');self.store.write(pid,'paper/main.md','# old')
        self.store.receipt(pid,'execution',{'status':'executed'})
        with patch.object(self.engine,'start'):
            self.engine.rerun(pid,4)
        self.assertFalse(self.store.path(pid,'results/metrics.json').exists())
        self.assertTrue(any(f['path'].startswith('audit/rerun-') for f in self.store.files(pid)))
        self.store.receipt(pid,'code',{'status':'generated'});self.store.update(pid,cursor=5,status='running')
        self.assertEqual(Store(self.tmp.name).get(pid)['status'],'awaiting_execution')

    def test_reconstructed_competition_runs_real_code_and_word_export(self):
        from http.server import ThreadingHTTPServer
        from test_app import FakeAPI
        server=ThreadingHTTPServer(('127.0.0.1',0),FakeAPI)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            self.store.save_settings({'endpoint':f'http://127.0.0.1:{server.server_port}/v1','model':'fake'})
            pid=self.pid('api','comp_cumcm',{'output_format':'docx'})
            self.engine.start(pid);p=self.wait(pid)
            for _ in range(4):
                if p['status']=='awaiting_execution':break
                self.assertEqual(p['status'],'review',p['error']);self.engine.start(pid);p=self.wait(pid)
            self.assertEqual(p['status'],'awaiting_execution',p['error'])
            self.engine.start(pid,'execute');p=self.wait(pid)
            for _ in range(4):
                if p['status']=='completed':break
                self.assertEqual(p['status'],'review',p['error']);self.engine.start(pid);p=self.wait(pid)
            self.assertEqual(p['status'],'completed',p['error'])
            self.assertTrue(self.store.path(pid,'results/execution.json').exists())
            self.assertTrue(self.store.path(pid,'exports/paper.docx').exists())
            self.assertFalse(self.store.path(pid,'exports/paper.pdf').exists())
        finally:server.shutdown();server.server_close()

if __name__=='__main__': unittest.main()
