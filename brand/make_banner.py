from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import math
PINE=(31,59,45); PINE_D=(20,40,30); HONEY=(217,147,15); HONEY_L=(240,186,72); WAX=(247,242,227)
F="fonts/"
def hexpts(cx,cy,r,rot=30):
    return [(cx+r*math.cos(math.radians(rot+60*i)), cy+r*math.sin(math.radians(rot+60*i))) for i in range(6)]

# ---------- avatar 800x800 (YouTube crops to circle) ----------
S=4; N=800*S
im=Image.new("RGB",(N,N),PINE); d=ImageDraw.Draw(im)
# subtle radial lift
glow=Image.new("L",(N,N),0); gd=ImageDraw.Draw(glow); gd.ellipse([N*0.1,N*0.05,N*0.9,N*0.85],fill=70)
glow=glow.filter(ImageFilter.GaussianBlur(N*0.12)); im.paste(Image.new("RGB",(N,N),(45,82,62)),(0,0),glow)
d=ImageDraw.Draw(im)
# 7-cell comb, pointy-top hexes
r=N*0.125; w=math.sqrt(3)*r; cx,cy=N/2,N/2
cells=[(0,0)]+[(w*math.cos(math.radians(a)), w*math.sin(math.radians(a))) for a in range(0,360,60)]
for i,(dx,dy) in enumerate(cells):
    fill = HONEY_L if i==0 else HONEY
    d.polygon(hexpts(cx+dx,cy+dy,r*0.9,30),fill=fill)
# bee in centre cell: body + wings, simple
bx,by=cx,cy
d.ellipse([bx-r*0.34,by-r*0.42,bx+r*0.34,by+r*0.6],fill=PINE)
for k in (-0.08,0.16,0.38):
    d.rectangle([bx-r*0.34,by+r*k-r*0.055,bx+r*0.34,by+r*k+r*0.055],fill=HONEY_L)
d.ellipse([bx-r*0.2,by-r*0.66,bx+r*0.2,by-r*0.3],fill=PINE)
d.ellipse([bx-r*0.78,by-r*0.62,bx-r*0.12,by-r*0.02],fill=WAX)
d.ellipse([bx+r*0.12,by-r*0.62,bx+r*0.78,by-r*0.02],fill=WAX)
d.ellipse([bx-r*0.34,by-r*0.42,bx+r*0.34,by+r*0.6],outline=PINE,width=int(r*0.05))
im=im.resize((800,800),Image.LANCZOS); im.save("out/yt-avatar.png")

# ---------- banner 2048x1152, safe area 1235x338 centred ----------
src=Image.open("picks/aerial-pasture2.jpg").convert("RGB")
W,H=2048,1152
sc=max(W/src.width,H/src.height); bg=src.resize((int(src.width*sc),int(src.height*sc)),Image.LANCZOS)
ox=(bg.width-W)//2; oy=int((bg.height-H)*0.62); bg=bg.crop((ox,oy,ox+W,oy+H))
bg=ImageEnhance.Color(bg).enhance(1.08); bg=ImageEnhance.Contrast(bg).enhance(1.05)
bg=bg.filter(ImageFilter.UnsharpMask(radius=2,percent=60,threshold=2))
# darken band behind safe area for legibility
shade=Image.new("L",(W,H),0); sd=ImageDraw.Draw(shade)
sd.rectangle([0,H/2-260,W,H/2+260],fill=150); shade=shade.filter(ImageFilter.GaussianBlur(120))
bg.paste(Image.new("RGB",(W,H),PINE_D),(0,0),shade)
d=ImageDraw.Draw(bg)
title=ImageFont.truetype(F+"Bricolage-Bold.ttf",90); sub=ImageFont.truetype(F+"Bricolage-Semibold.ttf",40)
t="Pachamama Valley Farm"; tw=d.textlength(t,font=title)
# badge left of title
import cairosvg, io
bsz=170
badge=Image.open(io.BytesIO(cairosvg.svg2png(url="/tmp/claude-0/-home-claude/a9cd29c9-59f6-5739-91f2-cc53916c9514/scratchpad/logo/pvf-logo.svg",output_width=bsz))).convert("RGBA")
gap=34; total=bsz+gap+tw
x0=(W-total)/2; yT=H/2-80
bg.paste(badge,(int(x0),int(H/2-bsz/2-20)),badge)
d.text((x0+bsz+gap,yT),t,font=title,fill=WAX)
s="Live from the bee yard  ·  Winnsboro, Texas"
sw=d.textlength(s,font=sub); d.text((x0+bsz+gap,H/2+40),s,font=sub,fill=HONEY_L)
bg.save("out/yt-banner.jpg",quality=88)
# preview with safe area outline
pv=bg.copy(); pd=ImageDraw.Draw(pv); pd.rectangle([(W-1235)/2,(H-338)/2,(W+1235)/2,(H+338)/2],outline=(255,0,0),width=3)
pv.resize((1024,576)).save("out/_banner_check.jpg",quality=80)
print("done")
