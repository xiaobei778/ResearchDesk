import json

CODE = '''import json, random, statistics
from pathlib import Path
random.seed(20261020)
metrics = []
for rate in (0.4, 0.7, 0.9):
    means = []
    for replication in range(10):
        arrival = finish = 0.0
        waits = []
        for i in range(12000):
            arrival += random.expovariate(rate)
            start = max(arrival, finish)
            if i >= 2000:
                waits.append(start-arrival)
            finish = start + random.expovariate(1.0)
        means.append(statistics.mean(waits))
    metrics.append({"name": f"到达率 {rate} 的平均等待时间", "value": statistics.mean(means), "unit": "时间单位"})
result = {"metrics": metrics, "dataset_origin": "simulation", "method": "M/M/1 队列，服务率1，每种到达率10次独立重复，每次12000客户，预热2000客户，固定随机种子20261020", "notes": ["演示仿真，不是真实观测数据", "有限样本，尚无置信区间与收敛验证"]}
Path('results').mkdir(exist_ok=True)
Path('results/metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2), encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
'''

def response(step, store, pid):
    project = store.get(pid)
    metrics = store.path(pid,'results/metrics.json')
    result = json.loads(metrics.read_text('utf-8')) if metrics.exists() else None
    table = '\n'.join(f"- {m['name']}：{m['value']:.4f} {m.get('unit','')}" for m in result['metrics']) if result else '计算尚未执行；没有实验数值。本文仅描述研究方案。'
    paper = f'''# 到达率对单服务台排队等待时间的影响：演示仿真

## 摘要
本项目演示从问题拆解到仿真和论文草稿的工作流。所有计算数据均来自本地随机模拟，不能视为实际服务系统的观测证据。

## 研究问题
在服务率固定为1的 M/M/1 队列中，比较不同到达率对应的平均等待时间。关注系统负载升高时等待时间的变化。

## 方法
采用事件递推模拟，固定随机种子20261020。到达间隔和服务时长分别服从指数分布。到达率取0.4、0.7、0.9，每个条件运行10次，每次12000名客户，前2000名作为预热阶段。数值来自实际执行的 Python 脚本；脚本及执行收据保存在项目中。

## 结果 / 待验证内容
{table}

## 讨论
{'本次仿真提示较高负载伴随更长等待。该表述仅适用于当前模拟假设与参数，不能直接推广到现实服务场景。' if result else '尚无实际执行的计算结果，不能对到达率的效果作经验结论。'}

## 局限
目前未报告跨重复试验的置信区间，未系统验证预热长度或收敛性，也未纳入现实队列中的放弃、优先级及非平稳到达。正常退出和产生指标只能验证执行链，不能验证模型正确性。

## 参考来源
此演示未检索外部文献，不列出虚构参考文献。后续应补充并核验排队论的真实来源。
'''
    docs = {
        'brief':'# 问题梳理\n\n比较三种到达率对单服务台平均等待时间的影响。\n\n资料来源：本地演示设计，无真实观测资料。\n\n交付：代码、实际运行指标、指标图和论文草稿。',
        'literature':'# 文献与证据\n\n当前没有导入或检索文献。演示不生成虚构引文。\n\n待查：M/M/1 稳态假设、预热方法、模拟置信区间。',
        'hypothesis':'# 假设与边界\n\n假设：在服务率为1时，增加到达率会增加平均等待时间。\n\n条件：泊松到达、指数服务、单服务台、先来先服务、无限等待空间、负载小于1。\n\n只研究仿真系统，不代表现实结论。',
        'plan':'# 仿真方案\n\n服务率固定1，到达率0.4/0.7/0.9。每条件10次重复，每次12000客户，预热2000。\n\n输出平均排队等待时间。随机种子20261020。\n\n审阅要点：假设是否合理；后续需增加收敛性和置信区间检查。',
        'code':CODE,
        'analysis':'# 结果核对\n\n'+table+'\n\n来源：本地实际执行的模拟代码。尚需独立检查模型与统计推断。' if result else '# 分析计划\n\n没有计算结果，只能描述待验证假设，不能声称实验完成。',
        'outline':'# 论文结构\n\n1. 摘要与仿真性质\n2. 问题和边界\n3. 可复现方法\n4. 结果或待验证方案\n5. 局限\n6. 核验后的参考来源',
        'write':paper,
        'review':'# 审稿记录\n\n已检查：仿真标识、结果与产物一致性、无虚构引用。\n\n需补充：置信区间、预热敏感性分析、真实理论来源。\n\n本演示审稿是预置示例，不是外部模型或同行评审。',
        'revise':paper,
    }
    return {'summary':'本地演示内容已生成；未调用 API', 'files':[{'path':path,'content': '# 修改记录\n\n明确标记仿真、证据来源及尚未验证的统计问题。' if path.endswith('change_log.md') else docs[step.id]} for path in step.outputs]}
