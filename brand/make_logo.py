import math, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

D = sys.argv[1] if len(sys.argv) > 1 else '.'
font = TTFont(D + '/fonts/Oswald-Bold.ttf')
gs = font.getGlyphSet(); cmap = font.getBestCmap(); hmtx = font['hmtx']
UPM = 1000; CAP = 810

PINE = '#2F4420'; CREAM = '#F5EDD6'; ORANGE = '#E9862A'; ORANGE2 = '#F3A545'
HONEY = '#F4C23D'; SUN1 = '#FFF4C8'; SUN2 = '#FAD56A'; HILL1 = '#76985A'; HILL2 = '#5A7B40'; HILL3 = '#486834'
C = 600.0

def glyph_path(ch, size, angle_deg, r, inward):
    """Place glyph centered at polar angle angle_deg (0 = up, clockwise), baseline at radius r.
    inward=False: letters stand outward (top arc). inward=True: letters hang inward (bottom arc, reads left->right)."""
    gname = cmap[ord(ch)]
    adv = hmtx[gname][0]
    s = size / UPM
    a = math.radians(angle_deg)
    # point on baseline circle
    px = C + r * math.sin(a); py = C - r * math.cos(a)
    if not inward:
        rot = angle_deg
        # glyph coords: x right, y up. Map to svg: rotate by rot around baseline point, flip y
        t = (s, 0, 0, -s, -adv * s / 2, 0)
    else:
        rot = angle_deg + 180
        t = (s, 0, 0, -s, -adv * s / 2, 0)
    pen = SVGPathPen(gs)
    gs[gname].draw(TransformPen(pen, t))
    d = pen.getCommands()
    return f'<path transform="translate({px:.2f},{py:.2f}) rotate({rot:.2f})" d="{d}"/>'

def text_on_arc(text, size, r, center_deg, inward, tracking=0.06):
    s = size / UPM
    advs = [hmtx[cmap[ord(c)]][0] * s + tracking * size for c in text]
    total = sum(advs) - tracking * size
    # for inward text, glyph sits on baseline r but extends inward; arc length measured at baseline
    span = math.degrees(total / r)
    out = []
    pos = -total / 2
    for c, w in zip(text, advs):
        mid = pos + (w - tracking * size) / 2
        ang = math.degrees(mid / r)
        if c != ' ':
            if inward:
                out.append(glyph_path(c, size, center_deg - ang, r, True))
            else:
                out.append(glyph_path(c, size, center_deg + ang, r, False))
        pos += w
    return out, span

def star(cx, cy, R, rot=0):
    pts = []
    for i in range(10):
        rr = R if i % 2 == 0 else R * 0.42
        a = math.radians(rot + i * 36)
        pts.append(f'{cx + rr * math.sin(a):.1f},{cy - rr * math.cos(a):.1f}')
    return f'<polygon points="{" ".join(pts)}" fill="{CREAM}"/>'

def hexagon(cx, cy, R):
    pts = [f'{cx + R * math.cos(math.radians(30 + 60 * i)):.1f},{cy + R * math.sin(math.radians(30 + 60 * i)):.1f}' for i in range(6)]
    return ' '.join(pts)

# ---- rings ----
R_OUT, R_CREAM1, R_BAND_OUT, R_BAND_IN, R_CREAM2, R_ART = 596, 584, 572, 424, 412, 400
parts = []
parts.append(f'<circle cx="600" cy="600" r="{R_OUT}" fill="{PINE}"/>')
parts.append(f'<circle cx="600" cy="600" r="{R_CREAM1}" fill="{CREAM}"/>')
parts.append(f'<circle cx="600" cy="600" r="{R_BAND_OUT}" fill="{PINE}"/>')
parts.append(f'<circle cx="600" cy="600" r="{R_CREAM2}" fill="{CREAM}"/>')

# ---- art disc ----
SUN = (600, 568)
art = [f'<rect x="0" y="0" width="1200" height="1200" fill="{ORANGE}"/>']
N = 24
for i in range(0, N, 2):
    a0 = math.radians(i * 360 / N - 3.75); a1 = math.radians((i + 1) * 360 / N - 3.75)
    L = 900
    art.append(f'<path d="M{SUN[0]},{SUN[1]} L{SUN[0] + L * math.sin(a0):.1f},{SUN[1] - L * math.cos(a0):.1f} L{SUN[0] + L * math.sin(a1):.1f},{SUN[1] - L * math.cos(a1):.1f} Z" fill="{ORANGE2}"/>')
art.append(f'<circle cx="{SUN[0]}" cy="{SUN[1]}" r="200" fill="{SUN2}" opacity="0.55"/>')
art.append(f'<circle cx="{SUN[0]}" cy="{SUN[1]}" r="170" fill="url(#sun)"/>')
# hills
art.append(f'<path d="M150,745 C330,665 480,700 620,735 C780,775 900,720 1060,690 L1060,1100 L150,1100 Z" fill="{HILL1}"/>')
art.append(f'<path d="M150,850 C360,790 520,830 680,858 C850,888 950,840 1060,820 L1060,1100 L150,1100 Z" fill="{HILL2}"/>')
art.append(f'<path d="M150,940 C380,905 560,925 760,945 C900,958 980,940 1060,925 L1060,1100 L150,1100 Z" fill="{HILL3}"/>')
# honeycomb cluster (3 on hill)
HR = 46
for (hx, hy) in [(600 - HR * 1.732, 820), (600, 820), (600 + HR * 1.732, 820)]:
    art.append(f'<polygon points="{hexagon(hx, hy, HR)}" fill="{HONEY}" stroke="{PINE}" stroke-width="9" stroke-linejoin="round"/>')
# drip
art.append(f'<path d="M588,861 C588,885 576,895 576,908 C576,922 600,922 600,908 C600,895 588,885 588,861 Z" fill="{HONEY}" stroke="{PINE}" stroke-width="6"/>')

# bee (centered on sun)
bx, by = 600, 560
bee = []
bee.append(f'<g stroke="{PINE}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round">')
# antennae
bee.append(f'<path d="M588,{by - 92} Q575,{by - 128} 552,{by - 138}" fill="none"/>')
bee.append(f'<path d="M612,{by - 92} Q625,{by - 128} 648,{by - 138}" fill="none"/>')
bee.append(f'<circle cx="550" cy="{by - 139}" r="9" fill="{PINE}"/><circle cx="650" cy="{by - 139}" r="9" fill="{PINE}"/>')
# wings
bee.append(f'<ellipse cx="528" cy="{by - 40}" rx="70" ry="38" fill="{CREAM}" transform="rotate(-22 528 {by - 40})"/>')
bee.append(f'<ellipse cx="672" cy="{by - 40}" rx="70" ry="38" fill="{CREAM}" transform="rotate(22 672 {by - 40})"/>')
bee.append(f'<ellipse cx="540" cy="{by - 8}" rx="48" ry="24" fill="{CREAM}" transform="rotate(-8 540 {by - 8})"/>')
bee.append(f'<ellipse cx="660" cy="{by - 8}" rx="48" ry="24" fill="{CREAM}" transform="rotate(8 660 {by - 8})"/>')
bee.append('</g>')
# abdomen
ab = f'M600,{by - 50} C548,{by - 50} 528,{by - 8} 528,{by + 40} C528,{by + 100} 562,{by + 140} 600,{by + 160} C638,{by + 140} 672,{by + 100} 672,{by + 40} C672,{by - 8} 652,{by - 50} 600,{by - 50} Z'
bee.append(f'<path d="{ab}" fill="{HONEY}"/>')
bee.append(f'<g clip-path="url(#abd)" fill="{PINE}"><rect x="500" y="{by + 2}" width="200" height="26"/><rect x="500" y="{by + 58}" width="200" height="26"/><rect x="500" y="{by + 112}" width="200" height="22"/></g>')
bee.append(f'<path d="{ab}" fill="none" stroke="{PINE}" stroke-width="9" stroke-linejoin="round"/>')
bee.append(f'<path d="M592,{by + 162} L600,{by + 182} L608,{by + 162} Z" fill="{PINE}"/>')
# head
bee.append(f'<circle cx="600" cy="{by - 78}" r="36" fill="{PINE}"/>')
bee.append(f'<circle cx="587" cy="{by - 86}" r="6" fill="{CREAM}"/><circle cx="613" cy="{by - 86}" r="6" fill="{CREAM}"/>')

defs = f'''<defs>
<clipPath id="art"><circle cx="600" cy="600" r="{R_ART}"/></clipPath>
<clipPath id="abd"><path d="{ab}"/></clipPath>
<radialGradient id="sun" cx="50%" cy="45%" r="60%"><stop offset="0%" stop-color="{SUN1}"/><stop offset="100%" stop-color="{SUN2}"/></radialGradient>
</defs>'''

parts.append(f'<g clip-path="url(#art)">' + ''.join(art) + ''.join(bee) + '</g>')

# ---- text ----
top, tspan = text_on_arc('PACHAMAMA VALLEY FARM', 98, 452, 0, False, tracking=0.08)
bot, bspan = text_on_arc('LOCAL TEXAS HONEY', 82, 538, 180, True, tracking=0.16)
parts.append(f'<g fill="{CREAM}">' + ''.join(top) + ''.join(bot) + '</g>')
# stars in the gaps
gap_mid = (tspan / 2 + (180 - bspan / 2)) / 2  # angle between end of top text and start of bottom text
for sgn in (1, -1):
    ang = math.radians(sgn * (90 + (gap_mid - 90)))
    ang = math.radians(sgn * gap_mid)
    rr = (R_BAND_OUT + R_BAND_IN) / 2
    parts.append(star(C + rr * math.sin(ang), C - rr * math.cos(ang), 34, rot=math.degrees(ang)))
sys.stderr.write(f'top span {tspan:.1f} deg, bottom span {bspan:.1f} deg, star at +/-{gap_mid:.1f}\n')

svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1200" width="1200" height="1200">{defs}' + ''.join(parts) + '</svg>'
open(D + '/pvf-logo.svg', 'w').write(svg)

# ---- simplified mark (no text) for favicon / small sizes ----
mark_parts = [f'<circle cx="600" cy="600" r="432" fill="{PINE}"/>', f'<circle cx="600" cy="600" r="{R_CREAM2}" fill="{CREAM}"/>',
              f'<g clip-path="url(#art)">' + ''.join(art) + ''.join(bee) + '</g>']
mark = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="168 168 864 864" width="864" height="864">{defs}' + ''.join(mark_parts) + '</svg>'
open(D + '/pvf-mark.svg', 'w').write(mark)
