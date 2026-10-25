import json
import math
import re
import zipfile
from html import escape
from pathlib import Path

def validate_metrics(data):
    if not isinstance(data, dict) or data.get('dataset_origin') not in ('simulation','uploaded','public'):
        raise ValueError('metrics.json 必须声明 dataset_origin: simulation / uploaded / public')
    if not str(data.get('method', '')).strip(): raise ValueError('metrics.json 缺少 method')
    metrics = data.get('metrics')
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 100:
        raise ValueError('metrics.json 需要 1 至 100 个指标')
    for m in metrics:
        if not isinstance(m, dict) or not str(m.get('name','')).strip(): raise ValueError('指标缺少名称')
        v = m.get('value')
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v): raise ValueError('指标值必须是有限数字')
    return data

def figures(store, pid):
    path = store.path(pid, 'results/metrics.json')
    if not path.exists():
        store.write(pid,'results/figures.md','# 图表\n\n没有已执行且有效的指标，本阶段未生成数据图。\n')
        return
    data = validate_metrics(json.loads(path.read_text('utf-8')))
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    def font(size):
        return ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default()
    # One axis per metric avoids misleading comparisons across different units.
    values = data['metrics'][:20]
    img = Image.new('RGB', (1100, 160 + len(values)*65), '#f8fafc')
    draw = ImageDraw.Draw(img)
    draw.text((35,25),'仿真指标（非真实观测）' if data['dataset_origin']=='simulation' else '已执行计算的指标',font=font(27),fill='#18243d')
    svg_rows = []
    for i,m in enumerate(values):
        y = 100+i*65
        label = str(m['name'])[:35]
        value = f"{m['value']:.6g} {m.get('unit','')}"
        draw.rounded_rectangle((32,y-5,1065,y+48),radius=10,fill='white')
        draw.text((50,y+5),label,font=font(21),fill='#273349')
        draw.text((760,y+5),value,font=font(21),fill='#087f74')
        svg_rows.append(f'<text x="40" y="{y+25}" font-size="20">{escape(label)}: {escape(value)}</text>')
    img.save(store.path(pid,'results/metrics.png'))
    store.write(pid,'results/metrics.svg',f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{img.height}"><rect width="100%" height="100%" fill="#f8fafc"/>' + ''.join(svg_rows) + '</svg>')
    rows = '\n'.join(f"| {m['name']} | {m['value']:.6g} | {m.get('unit','')} |" for m in data['metrics'])
    store.write(pid,'results/figures.md',f"# 实际运行指标\n\n数据来源：{data['dataset_origin']}\n\n| 指标 | 数值 | 单位 |\n| --- | --- | --- |\n{rows}\n\n![指标卡片](metrics.png)\n\n图只呈现计算数值，不代表科学有效性已验证。\n")

def export_paper(store, pid):
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
    project = store.get(pid)
    paper = store.path(pid,'paper/main.md')
    if not paper.exists() or not paper.read_text('utf-8').strip(): raise ValueError('缺少论文正文，无法导出')
    text = paper.read_text('utf-8')
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
    style.font.size = Pt(10.5)
    style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    doc.core_properties.title = project['title']
    doc.add_paragraph('ResearchDesk · 本地演示 / 仿真示例' if project['mode']=='demo' else 'ResearchDesk · 研究草稿，请核验证据后使用', 'Subtitle')
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    normal = ParagraphStyle('cn',fontName='STSong-Light',fontSize=10.5,leading=17,spaceAfter=7,wordWrap='CJK',alignment=TA_LEFT)
    story = [Paragraph(escape('演示 / 仿真示例' if project['mode']=='demo' else '研究草稿 · 需人工核验'),normal),Spacer(1,12)]
    code = False
    for line in text.splitlines():
        if line.startswith('```'):
            code = not code
            continue
        if not line.strip():
            story.append(Spacer(1,5))
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)',line)
        cleaned = re.sub(r'\*\*(.*?)\*\*',r'\1', line)
        if heading:
            level = min(len(heading[1]),4)
            doc.add_heading(heading[2],level)
            h = ParagraphStyle('h', parent=normal,fontSize=19-level*2,leading=24-level,spaceBefore=10)
            story.append(Paragraph(escape(heading[2]),h))
        else:
            doc.add_paragraph(cleaned)
            story.append(Paragraph(escape(cleaned),normal))
    image = store.path(pid,'results/metrics.png')
    if image.exists():
        doc.add_heading('实际运行指标附图',2)
        doc.add_picture(str(image),width=Inches(6))
        from PIL import Image as PILImage
        with PILImage.open(image) as im: w,h=im.size
        story.extend([Spacer(1,12),Image(str(image),width=470,height=min(620,470*h/w))])
    output_format=project.get('options',{}).get('output_format','both')
    if output_format in ('both','docx'): doc.save(store.path(pid,'exports/paper.docx'))
    if output_format in ('both','pdf'): SimpleDocTemplate(str(store.path(pid,'exports/paper.pdf')),pagesize=A4,rightMargin=48,leftMargin=48,topMargin=48,bottomMargin=48,title=project['title']).build(story)
    events, receipts = store.history(pid)
    store.write(pid,'exports/provenance.json',json.dumps({'project':project,'receipts':receipts,'notice':'执行成功仅表示程序退出并形成指标文件，科研结论仍需核验。'},ensure_ascii=False,indent=2))
    store.write(pid,'exports/README.md','# 导出说明\n\n包含 Markdown 原文、Word、PDF、资料、代码、真实运行收据和流程记录。\n\n首版导出支持基础标题/段落与指标附图；复杂公式、参考文献样式、表格布局仍需人工排版。\n')
    package = store.path(pid,'exports/project.zip')
    root = package.parent.parent
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for f in store.files(pid):
            p = store.path(pid,f['path'])
            if p == package: continue
            z.write(p,f['path'])
    return {'files': ['exports/paper.docx','exports/paper.pdf','exports/project.zip']}
