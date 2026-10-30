"""Optional PDF edition: ReportLab 4.5.0 and Cyrillic TrueType fonts required."""
from pathlib import Path
import re
import html
import argparse
import math
import xml.etree.ElementTree as ET
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, PageBreak, NextPageTemplate, Image, Preformatted, Flowable, KeepTogether

ROOT=Path(__file__).resolve().parents[1]


class SvgDiagram(Flowable):
    def __init__(self,path,width):
        Flowable.__init__(self)
        self.xml=ET.parse(path).getroot(); self.width=width; self.scale=width/float(self.xml.attrib["width"]); self.height=float(self.xml.attrib["height"])*self.scale

    def draw(self):
        c=self.canv; c.saveState(); c.translate(0,self.height); c.scale(self.scale,-self.scale)
        def render(el,inherit):
            at={**inherit,**el.attrib}; tag=el.tag.split("}")[-1]
            if tag in ("defs","marker"): return
            stroke=at.get("stroke","none"); fill=at.get("fill","#000000")
            c.setLineWidth(float(at.get("stroke-width",1)))
            if stroke!="none": c.setStrokeColor(colors.HexColor(stroke))
            if fill!="none": c.setFillColor(colors.HexColor(fill))
            if tag=="rect":
                c.roundRect(float(at.get("x",0)),float(at.get("y",0)),float(at["width"]),float(at["height"]),float(at.get("rx",0)),stroke=int(stroke!="none"),fill=int(fill!="none"))
            elif tag=="text":
                c.saveState(); c.translate(float(at["x"]),float(at["y"])); c.scale(1,-1); c.setFont("Body",float(at.get("font-size",20))); c.drawString(0,0,"".join(el.itertext())); c.restoreState()
            elif tag=="path":
                values=[float(x) for x in re.findall(r"-?\d+(?:\.\d+)?",at["d"])]
                points=list(zip(values[::2],values[1::2])); p=c.beginPath(); p.moveTo(*points[0])
                for pt in points[1:]: p.lineTo(*pt)
                c.drawPath(p,stroke=1,fill=0)
                if at.get("marker-end") and len(points)>1:
                    (x0,y0),(x1,y1)=points[-2:]; angle=math.atan2(y1-y0,x1-x0)
                    p=c.beginPath(); p.moveTo(x1,y1)
                    for sign in (-1,1): p.lineTo(x1-12*math.cos(angle)+sign*5*math.sin(angle),y1-12*math.sin(angle)-sign*5*math.cos(angle))
                    p.close(); c.setFillColor(colors.HexColor(stroke)); c.drawPath(p,stroke=0,fill=1)
            for child in el: render(child,at)
        render(self.xml,{})
        c.restoreState()


def inline(text):
    text=html.escape(text)
    text=re.sub(r"\*\*(.+?)\*\*",r"<b>\1</b>",text)
    text=re.sub(r"`([^`]+)`",r'<font color="#006d77">\1</font>',text)
    def link(m):
        label,url=m.groups()
        if url.startswith("https://"): return f'<link href="{url}" color="#006d77">{label}</link>'
        return label
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)",link,text).replace("—","-").replace("–","-").replace("‑","-")


def build(font,bold):
    pdfmetrics.registerFont(TTFont("Body",str(font)))
    pdfmetrics.registerFont(TTFont("BodyBold",str(bold)))
    pdfmetrics.registerFontFamily("Body",normal="Body",bold="BodyBold",italic="Body",boldItalic="BodyBold")
    styles={
        "body":ParagraphStyle("body",fontName="Body",fontSize=10.2,leading=14.5,spaceAfter=8,textColor=colors.HexColor("#152738")),
        "h1":ParagraphStyle("h1",fontName="BodyBold",fontSize=23,leading=28,spaceAfter=16,textColor=colors.HexColor("#006d77")),
        "h2":ParagraphStyle("h2",fontName="BodyBold",fontSize=15,leading=20,spaceBefore=16,spaceAfter=10,keepWithNext=True,textColor=colors.HexColor("#006d77")),
        "h3":ParagraphStyle("h3",fontName="BodyBold",fontSize=11.5,leading=16,spaceBefore=10,spaceAfter=8,keepWithNext=True),
        "table":ParagraphStyle("table",fontName="Body",fontSize=8.3,leading=11,spaceAfter=2),
        "code":ParagraphStyle("code",fontName="Body",fontSize=8.2,leading=11,spaceBefore=8,spaceAfter=12,backColor=colors.HexColor("#eef4f6")),
        "list":ParagraphStyle("list",fontName="Body",fontSize=10.2,leading=14.5,leftIndent=16,firstLineIndent=0,bulletIndent=0,spaceAfter=6),
    }
    w,h=A4; lw,lh=landscape(A4); bodyw=w-90
    def footer(canvas,doc):
        canvas.setFont("Body",8); canvas.setFillColor(colors.HexColor("#536673")); pw,ph=canvas._pagesize
        canvas.drawString(32,12,"GWI-X v1.2 | SYNTHETIC | 29.10.2026"); canvas.drawRightString(pw-32,12,str(doc.page))
    doc=BaseDocTemplate(str(ROOT/"docs/technical_report_ru.pdf"),pagesize=A4,title="GWI-X v1.2 - технический отчёт: синтетическая модель",author="GWI-X project",allowSplitting=1,invariant=1)
    doc.addPageTemplates([
        PageTemplate(id="portrait",frames=Frame(45,40,bodyw,h-85,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0),onPage=footer,pagesize=A4),
        PageTemplate(id="landscape",frames=Frame(35,25,lw-70,lh-50,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0),onPage=footer,pagesize=(lw,lh))
    ])
    lines=(ROOT/"docs/technical_report_ru.md").read_text(encoding="utf-8").splitlines(); story=[]; figures=[]; i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1; continue
        if line.startswith("```"):
            code=[]; i+=1
            while i<len(lines) and not lines[i].startswith("```"): code.append(lines[i]); i+=1
            story.append(KeepTogether([Preformatted("\n".join(code),styles["code"],maxLineLength=98)])); i+=1; continue
        if line.startswith("!["):
            name=re.search(r"\]\(([^)]+)\)",line).group(1)
            target=(ROOT/"docs"/name).resolve()
            figures.append(target)
            caption=re.search(r"!\[([^\]]*)\]",line).group(1)
            story.append(Paragraph(inline(f"Рисунок {len(figures)}. {caption}. См. графическое приложение в конце отчёта."),styles["body"]))
            i+=1; continue
        if line.startswith("|"):
            data=[]
            while i<len(lines) and lines[i].strip().startswith("|"):
                cells=[x.strip() for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?",x) for x in cells): data.append(cells)
                i+=1
            n=len(data[0]); widths=[bodyw/n]*n
            if n==2: widths=[bodyw*.37,bodyw*.63]
            if n==4: widths=[bodyw*.23,bodyw*.22,bodyw*.25,bodyw*.30]
            if n==5: widths=[bodyw*.21]+[bodyw*.1975]*4
            contents=[[Paragraph(inline(("**"+x+"**") if r==0 else x),styles["table"]) for x in cells] for r,cells in enumerate(data)]
            t=Table(contents,colWidths=widths,repeatRows=1,hAlign="LEFT")
            t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#dcecf0")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f3f6f8")]),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LINEBELOW",(0,0),(-1,0),.7,colors.HexColor("#86a8b3"))]))
            story.append(KeepTogether([t,Spacer(1,10)])); continue
        if line.startswith("#"):
            level=len(line)-len(line.lstrip("#")); story.append(Paragraph(inline(line[level:].strip()),styles["h"+str(min(level,3))])); i+=1; continue
        bullet=re.match(r"^(- |\d+\. )(.*)",line)
        if bullet:
            story.append(Paragraph(inline(bullet.group(2)),styles["list"],bulletText=bullet.group(1).strip())); i+=1; continue
        para=[line]; i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r"^(#|\||!\[|```|- |\d+\. )",lines[i].strip()): para.append(lines[i].strip()); i+=1
        story.append(Paragraph(inline(" ".join(para)),styles["body"]))
    for target in figures:
        story.extend([NextPageTemplate("landscape"),PageBreak()])
        if target.name=="architecture.svg": story.extend([Spacer(1,65),SvgDiagram(target,lw-70)])
        else:
            png=target.with_suffix(".png")
            if not png.exists(): raise RuntimeError("Generate PNG charts with Pillow first")
            height=lh-52; width=height*1500/1140
            story.append(Image(str(png),width=width,height=height))
    doc.build(story)


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--font",default="C:/Windows/Fonts/arial.ttf"); p.add_argument("--bold",default="C:/Windows/Fonts/arialbd.ttf"); a=p.parse_args(); build(a.font,a.bold)
