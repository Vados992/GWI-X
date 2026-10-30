"""Portable static SVG renderer. Optional Pillow renders the same plot to PNG."""
from html import escape
from pathlib import Path

COLORS=("#006d77","#d1495b","#815ac0","#b16b00")


def panel_chart(path,title,panels,subtitle,footer="SYNTHETIC SCENARIOS. No national calibration or causal effect established.",distinct_styles=False):
    width,height=1500,1140
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#f7f9fb"/>']
    raster=[]
    def line(x1,y1,x2,y2,color="#d0d7de",stroke=1,dash=None):
        style=f' stroke-dasharray="{dash[0]} {dash[1]}"' if dash else ''
        svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{stroke}"{style}/>')
        raster.append(("line",(x1,y1,x2,y2),color,stroke,dash))
    def label(x,y,text,size=20,color="#152738"):
        svg.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" fill="{color}">{escape(str(text))}</text>')
        raster.append(("text",(x,y-size),str(text),size,color))
    label(50,55,title,32); label(50,90,subtitle,19)
    for i,(heading,unit,series) in enumerate(panels):
        left=90+(i%2)*735; top=170+(i//2)*440
        pw,ph=600,290
        label(left-25,top-32,heading,25); label(left-25,top-5,unit,18)
        vals=[v for _,points in series for _,v in points if v is not None]
        if not vals: continue
        lo,hi=min(vals),max(vals)
        if lo==hi: lo-=1;hi+=1
        margin=(hi-lo)*.12; lo-=margin; hi+=margin
        years=sorted({x for _,points in series for x,v in points})
        xmin,xmax=min(years),max(years)
        X=lambda x:left+(x-xmin)/max(1,xmax-xmin)*pw
        Y=lambda y:top+ph-(y-lo)/(hi-lo)*ph
        for tick in range(5):
            v=lo+(hi-lo)*tick/4; y=Y(v)
            line(left,y,left+pw,y)
            label(left-70,y+7,f"{v:.2f}" if hi-lo<2 else f"{v:.1f}",17)
        shown=years[::2]
        if shown[-1]!=years[-1]:
            if distinct_styles and len(shown)>1 and years[-1]-shown[-1]<2: shown.pop()
            shown.append(years[-1])
        for x in shown: label(X(x)-22,top+ph+28,str(x),17)
        if lo<0<hi: line(left,Y(0),left+pw,Y(0),"#687788",2)
        for k,(name,points) in enumerate(series):
            color=COLORS[k]
            dash=((10,5) if k==1 else (3,5) if k==2 else None) if distinct_styles else None
            valid=[(X(x),Y(v)) for x,v in points if v is not None]
            for a,b in zip(valid,valid[1:]): line(*a,*b,color,3,dash)
            for x,y in valid:
                svg.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{color}"/>')
                raster.append(("circle",(x-3.5,y-3.5,x+3.5,y+3.5),color))
            ly=top+ph+60+(k//2)*25
            lx=left+(k%2)*300
            line(lx,ly-7,lx+30,ly-7,color,4,dash); label(lx+40,ly,name,18)
    label(50,1110,footer,19)
    svg.append("</svg>")
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("\n".join(svg),encoding="utf-8",newline="\n")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    im=Image.new("RGB",(width,height),"#f7f9fb"); d=ImageDraw.Draw(im)
    for op in raster:
        if op[0]=="line":
            if op[4]:
                import math
                x1,y1,x2,y2=op[1]; length=math.hypot(x2-x1,y2-y1)
                if length:
                    step,gap=op[4]; position=0
                    while position<length:
                        end=min(position+step,length)
                        d.line((x1+(x2-x1)*position/length,y1+(y2-y1)*position/length,x1+(x2-x1)*end/length,y1+(y2-y1)*end/length),fill=op[2],width=op[3])
                        position+=step+gap
            else: d.line(op[1],fill=op[2],width=op[3])
        elif op[0]=="circle": d.ellipse(op[1],fill=op[2])
        else: d.text(op[1],op[2],font=ImageFont.load_default(size=op[3]),fill=op[4])
    im.save(path.with_suffix(".png"))


def charts(root,results,comparisons):
    root=Path(root)
    reform,baseline=results["reform"],results["baseline"]
    metrics=(("Public debt / GDP","%","debt_gdp",100),("Consumer prices","CPI index; 2027 = 100","cpi",100),("Employment / eligible adults","%","employment_rate",100),("Real disposable household income","billion base-year CU / year","hh_real_disposable",1e-9))
    panels=[]
    for title,unit,key,scale in metrics:
        panels.append((title,unit,[(name,[(a["year"],a[key]*scale) for a in result.annual]) for name,result in (("Reform",reform),("No reform",baseline))]))
    panel_chart(root/"overview.svg","GWI-X v1.2 | Ten-year linked model",panels,"Fixed synthetic population; annual timing; fully disclosed financing")
    panels=[]
    for title,unit,key in (("Real GDP vs own control","% difference","gdp_real_change_pct"),("Real household income vs control","% difference","real_income_change_pct"),("Inflation vs own control","percentage points","inflation_change_pp"),("Employment vs own control","percentage points","employment_change_pp")):
        panels.append((title,unit,[(name,[(a["year"],a[key]) for a in comparisons if a["scenario"]==name]) for name in ("reform","recession","supply_inflation","combined")]))
    panel_chart(root/"stress_comparison.svg","Stress cases compared with the same shocks, without reform",panels,"Lines are scenarios, not statistical confidence intervals")
    panels=[]
    for title,unit,key,scale in (("Income and insurance clearing","billion nominal CU / year","income_fund",1e-9),("Liquid programme reserve","billion nominal CU at year end","reserve_close",1e-9),("Public investment","billion nominal CU / year","investment",1e-9),("Debt under financing stress","% of nominal GDP","debt_gdp",100)):
        panels.append((title,unit,[(n,[(a["year"],a[key]*scale) for a in results[n].annual]) for n in ("reform","funding_loss","debt_stress","zero_funding")]))
    # First panel explicitly includes income only; clearing is a separate series in CSV.
    panels[0]=("Income Fund payouts","billion nominal CU / year",panels[0][2])
    panel_chart(root/"funding_stress.svg","Funding constraints stop unsupported calculations",panels,"A truncated line ends at the last fully financed year; see status.json")
