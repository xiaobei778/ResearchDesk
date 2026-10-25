"""ResearchDesk executable workflows with application-owned output contracts."""
import json
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
RECIPES=json.loads((ROOT/'catalog/recipes.json').read_text('utf-8'))['templates']
INSTRUCTIONS={
 'data-quality':'只读取实际上传CSV或本机问卷导入的答卷；核验字段、缺失、重复和来源。没有真实数据时停止，不能用合成答卷替代。',
 'submission-package':'将实际论文、代码、计算结果与运行收据组成提交候选包；依据赛题另行人工核验文件名、匿名要求和格式。不宣称已提交或官方合规。',
 'survey-plan':'依据团队真实问题拟定调查目标、总体与抽样框、纳入标准、变量、偏差、伦理和预期样本量计算方法。不能虚构受访者、回收率或既有答卷。',
 'survey-questionnaire':'根据研究构念草拟清晰中性的问卷问题与选项，区分筛选题、量表与开放题，列知情说明与试测检查表。问题需人工定稿，本机问卷中心负责真实填写和导出；不生成替代真实答卷。',
 'research-lit':'围绕研究问题整理真实文献。先用 search_literature 检索候选元数据，再结合上传材料区分共识、分歧、方法与空白。不把元数据当作读过全文。BibTeX 只能来自提供的 DOI/作者/年份，缺来源则留待核验条目。',
 'idea-creator':'提出3个不同的可检验研究方向，每个给出假设、现实依据、数据需求、基线、预期贡献和最小验证实验。避免把概念重命名当作创新。',
 'novelty-check':'对候选 idea 的关键主张逐项检索，列最接近工作、相同点、区别及无法核验项。没有完整检索与全文时不宣称首创或无相关工作。',
 'research-review':'以独立评审角色评价问题、创新性、方法、可行性、统计设计和证据风险，给出必须修改项及可执行建议。',
 'research-refine-pipeline':'根据评审精炼选定方案，形成明确研究合同和实验计划；包含变量、对照、消融、重复次数、随机种子、失败条件、算力和数据来源。不得代替实际实验。',
 'paper-plan':'围绕目标场景规划论文结构，建立论点—证据—图表对应表，明确未完成实验和缺失引用。英文模板正文按指定语言输出。',
 'paper-plan-zh':'规划中文论文结构，逐节列论证目的、证据、图表与字数，识别缺失数据。',
 'paper-analysis':'依据实际执行收据和上传数据分析结果。明确数据来源、方法假设、误差、敏感性与局限；未运行则只输出分析计划，不生成实验数值。',
 'paper-figure-drawio':'生成可编辑 SVG 流程图，呈现方法模块、输入输出和逻辑依赖。SVG 必须自包含，禁止脚本、外链和嵌入 HTML。另写图注，不能画不存在的结果。',
 'paper-write':'基于提纲、已核验材料和实际执行结果撰写完整论文 Markdown，使用指定语言。包含摘要、相关工作、方法、结果或待验证方案、讨论、局限和真实参考来源。',
 'paper-write-zh':'撰写符合中文学术表达的完整论文，区分实际结果与待验证方案，所有引用须可追溯到已有来源。',
 'paper-write-nature':'用面向广泛学科读者的英文叙事写研究草稿，清晰表达问题、证据链、结论和局限；不承诺达到任何期刊录用标准。',
 'comp-prob-analysis':'逐问拆解竞赛题目，列目标、给定数据、未知量、约束、评分关注点、问题依赖和交付表。上传题目优先，缺题目时明确停止猜题。',
 'comp-modeling':'针对每个问题提出候选模型并比较，建立符号表、假设、目标函数、约束、求解步骤、基准方法、敏感性和检验方案。',
 'comp-stats-topic':'设计统计建模选题，明确研究对象、数据可获得性、抽样与偏差、解释变量、因变量、统计假设及验证方式。',
 'comp-review':'核验题目各问是否覆盖、模型假设是否合理、代码与指标是否对应、单位和图表是否一致、结论是否超出证据；给出逐项修正。',
 'comp-paper-zh':'按中文建模论文结构完成摘要、问题重述、假设、符号、模型、求解、实际结果、检验与推广。没有结果时标为建模方案。',
 'comp-paper-huawei-zh':'按研究生建模论文深度组织中文正文，强调模型推导、算法复杂度、数值验证和敏感性分析，引用与计算须有真实来源。',
 'comp-paper-en':'Write a complete English modeling paper with a summary, assumptions, notation, models, solution methods, observed or simulated results, validation and limitations. Never invent numerical results or references.',
 'thesis-proposal':'撰写开题报告：研究背景、真实文献现状、问题与意义、内容、技术路线、可行性、进度和预期成果。预期成果必须用未来时态。',
 'literature-review':'围绕明确问题形成综述。先检索并核验来源，建立纳入/排除标准、主题分类、比较表、争议与研究空白。未读全文的来源明确标记。',
 'course-plan':'根据课程与作业要求建立论点、提纲、材料与引用计划，明确论证方法和字数约束。',
 'course-paper':'基于课程要求、材料与提纲写完整课程论文，保留真实引用和独立分析，缺少证据时明确标注。',
 'course-report-plan':'整理课程项目的真实功能、实现过程、数据与测试证据，区分已实现和计划，形成报告提纲。',
 'course-report':'写课程设计报告，包括需求、设计、实现、真实测试、结果和不足；不得把规划功能当成已实现。',
 'humanities-plan':'建立人文社科问题、理论框架、原始材料、分析方法和伦理边界；不把数据建模强加到不适合的题目。',
 'humanities-write':'撰写人文社科学术草稿，围绕论点与原始材料论证，区分史料事实、他人观点和自己的推断。',
 'assets-inventory':'清点上传资产，列路径、类型、可用信息、来源、授权未知项、数据质量和缺失证据。只记录实际存在的文件。',
 'dev-requirement':'形成毕业设计需求规格：目标用户、核心流程、功能、非功能要求、验收标准、数据结构和项目边界。',
 'dev-design':'基于需求设计模块、接口、数据库 schema.sql、交互与测试计划。可运行性必须留给后续实际验证。',
 'dev-code':'生成可审阅的 Python 项目原型及运行说明。只能生成项目内文件，不联网、不安装依赖、不访问密钥。不得宣称未执行的程序已经测试成功。',
 'dev-selfcheck':'根据实际文件和执行收据核对需求覆盖，记录能证实的测试结果、未测试项和缺陷；没有执行记录不得编造通过。',
 'copyright-draft':'基于真实软件资料整理软件著作权申请信息草稿，未知作者、权利归属、版本与日期留空标待确认，不提供虚假登记事实。',
 'copyright-build':'将已确认信息整理为申请材料清单、软件说明书和生成报告，缺少代码或权属证据时明确列缺口。',
 'patent-draft':'整理技术交底书：现有技术、具体技术问题、结构或步骤、实施例、可替代方案、附图说明。不能保证新颖性与可授权性。',
 'patent-build':'根据技术草稿与确认事实形成完整交底书 Markdown，区分事实、推断和待验证效果；不虚构实验或法律结论。',
}
CODE_INSTRUCTION='生成可复现 Python 计算脚本，读取本项目已有数据或方案中明确声明的仿真；不得联网、安装依赖、读取项目外文件或访问密钥。使用固定随机种子。必须写 results/metrics.json，格式 {"metrics":[{"name":"指标","value":有限数字,"unit":""}],"dataset_origin":"simulation|uploaded|public","method":"实际方法","notes":[]}。数值须由计算产生，不能写死。代码将由用户审阅后执行；现在不要声称实验已完成。'
SOURCE_SKILLS=set(s['skill'] for r in RECIPES for s in r['steps'])

def options_valid(value=None):
    value=value or {}
    result={'language':value.get('language','zh'),'output_format':value.get('output_format','both'),
        'skip_figures':bool(value.get('skip_figures',False)),'skip_diagrams':bool(value.get('skip_diagrams',False)),
        'enable_review':bool(value.get('enable_review',True)),'max_rounds':max(1,min(5,int(value.get('max_rounds',1)))),
        'requirements':str(value.get('requirements',''))[:12000],
        'research_type':value.get('research_type','auto'),'discipline':str(value.get('discipline','auto'))[:100],
        'degree_level':value.get('degree_level','journal'),'stop_after_plan':bool(value.get('stop_after_plan',False))}
    if result['language'] not in ('zh','en') or result['output_format'] not in ('both','docx','pdf'): raise ValueError('语言或输出格式无效')
    if result['research_type'] not in ('auto','experimental','computational','simulation','clinical','econometric','survey','qualitative','theoretical','mixed'):raise ValueError('研究方法无效')
    if result['degree_level'] not in ('course','bachelor','master','doctor','journal'):raise ValueError('学位类型无效')
    return result

def resolve_workflow(template,options,Step):
    r=next((x for x in RECIPES if x['id']==template),None)
    if not r: return None
    opts=options_valid(options)
    steps=[]
    export_paths=tuple('exports/paper.'+ext for ext in ('docx','pdf') if opts['output_format'] in ('both',ext))
    def add(skill,name,outputs,instruction='',review=False,local=False,kind='model',role='writer'):
        steps.append(Step(f'{template}__{len(steps)}',name,role,tuple(outputs),instruction,review,local,kind,skill))
    has_paper=False
    for original in r['steps']:
        skill=original['skill'];name=original['name']
        if skill in ('data-quality','submission-package'):
            add(skill,name,original['outputs'],INSTRUCTIONS[skill],original['review'],local=True,kind='data_audit' if skill=='data-quality' else 'submission')
            continue
        if opts['research_type'] in ('qualitative','theoretical') and skill in ('experiment-bridge','comp-code','paper-analysis','paper-figure','nature-figure'):continue
        if opts['stop_after_plan'] and skill in ('comp-code','experiment-bridge','paper-analysis','paper-write','paper-write-zh','paper-write-nature','comp-paper-zh','comp-paper-en','comp-paper-huawei-zh','course-paper','course-report','humanities-write','dev-code'):
            break
        if skill in ('comp-code','experiment-bridge'):
            contract=CODE_INSTRUCTION+(' 本项目必须读取实际上传或本机问卷导入的数据，禁止用仿真或合成答卷替代；dataset_origin 必须是 uploaded。' if template in ('survey_market','comp_mathorcup_bigdata') else '')
            add(skill,name+' · 代码',('code/experiment.py',),contract,kind='code',role='coder')
            add('result-analysis','执行结果与分析',('results/analysis.md',),INSTRUCTIONS['paper-analysis'])
            continue
        if skill in ('paper-figure','nature-figure'):
            if not opts['skip_figures']: add(skill,'真实指标图',('results/figures.md',),local=True,kind='figures')
            continue
        if skill=='paper-figure-drawio':
            if not opts['skip_diagrams']: add(skill,'方法流程图',('figures/method.svg','figures/caption.md'),INSTRUCTIONS[skill])
            continue
        if skill in ('paper-compile','paper-compile-zh','comp-compile-zh','comp-compile-en','docx-export'):
            add(skill,'文稿导出',export_paths,local=True,kind='export')
            continue
        if skill in ('auto-paper-improvement-loop','auto-review-loop'):
            for i in range(opts['max_rounds']):
                add(skill,f'第 {i+1} 轮独立审稿',('paper/review.md',),INSTRUCTIONS['research-review'],role='reviewer')
                add('paper-revision',f'第 {i+1} 轮修订',('paper/main.md','paper/change_log.md'),'根据评审与实际证据修订完整论文，保留所有事实边界；修改日志逐条回应。')
                has_paper=True
            continue
        if skill=='comp-review' and not opts['enable_review']: continue
        outputs=list(original['outputs'])
        if skill in ('paper-write','paper-write-zh','paper-write-nature','comp-paper-zh','comp-paper-en','comp-paper-huawei-zh','course-paper','course-report','humanities-write','thesis-proposal','literature-review','patent-build'):
            # Portable Markdown writing replaces native-only TeX/Word generation honestly.
            outputs=['paper/main.md']+(['paper/references.bib'] if skill.startswith('paper-write') else [])
            has_paper=True
        if skill=='paper-analysis': outputs=['results/analysis.md']
        if skill=='assets-inventory': outputs=['docs/assets_inventory.md']
        if skill=='dev-code': outputs=['code/prototype.py','RUN.md']
        if opts['research_type'] in ('qualitative','theoretical') and skill in ('paper-figure','nature-figure','paper-analysis','experiment-bridge'):continue
        review=original['review'] or skill in ('research-refine-pipeline','comp-modeling','thesis-proposal','paper-write','paper-write-zh','paper-write-nature','comp-paper-zh','comp-paper-en','comp-paper-huawei-zh')
        role='reviewer' if skill in ('research-review','comp-review','dev-selfcheck') else 'coder' if skill=='dev-code' else 'planner' if any(s in skill for s in ('plan','idea','novelty','model','research','requirement','design')) else 'writer'
        add(skill,name,outputs,INSTRUCTIONS.get(skill,'依据实际材料完成当前步骤，明确缺失信息，不虚构证据。'),review,role=role)
    if has_paper and not any(s.kind=='export' for s in steps): add('document-export','导出最终文稿',export_paths,local=True,kind='export')
    return steps

def install(templates,by_id,Step):
    for old in templates.values(): old['legacy']=True
    for r in RECIPES:
        steps=resolve_workflow(r['id'],{},Step)
        for s in steps: by_id[s.id]=s
        templates[r['id']]={'name':r['name'],'description':r['description'] or '按独立重建的步骤推进并保留产物',
            'category':r['category'],'steps':[s.id for s in steps],'legacy':False,
            'baseline':r['steps'],'implementation':'ResearchDesk · Markdown / Word / PDF'}

def skill_catalog():
    return [{'id':k,'instruction':INSTRUCTIONS.get(k,CODE_INSTRUCTION if k in ('experiment-bridge','comp-code') else '本地工具或独立审稿/导出实现'),
        'templates':[r['name'] for r in RECIPES if any(s['skill']==k for s in r['steps'])],
        'origin':'ResearchDesk 工作流指导语；功能名称保留兼容标识'} for k in sorted(SOURCE_SKILLS)]
