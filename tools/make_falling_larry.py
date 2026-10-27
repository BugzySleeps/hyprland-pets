#!/usr/bin/env python3
"""Draws Larry's upright poses from his standing picture (src/larry.png):

  src/larry-falling.png   thrown / falling: stands up, front legs raised like arms
  src/larry-held.png      held: the same pose with all four legs waddling, 8 frames side by side
  src/larry-held.json     frame count and size, for sprites.py
  src/larry-typing.png    sitting on his butt with a mini keyboard on his lap, tapping it with his
                          front legs: 8 frames (+ larry-typing.json)
  src/larry-riding.png    sitting on a vehicle, side on: front legs reaching forward to the handlebars,
                          back legs pedalling (8 frames, one turn of the pedals; + larry-riding.json,
                          which also says where his seat and the pedals' middle are in the frame)

His head is cut from the original drawing; body, arms, legs, hooves and tail are drawn here in
the same style (thick black outline, white fill). Run it again after changing anything below.
"""
import json
import math
import sys
from pathlib import Path

import cairo
from PIL import Image, ImageChops, ImageDraw

SRC = Path(__file__).resolve().parent.parent / "src"
LW = 11          # outline width, matching the drawing
LIMB = 40        # limb thickness (the white part)
K = 0.8          # the drawn body is a bit smaller than the head's own scale
HEAD_AT = (-10, 70)
HEAD_CUT = [(185, 0), (511, 0), (511, 343), (440, 343), (345, 340), (326, 306), (311, 283), (301, 250),
            (293, 200), (287, 160), (185, 160)]   # larry.png pixels: everything above the neck
ARM_L = [(270, 470), (190, 400), (170, 300), (150, 210)]
ARM_R = [(440, 470), (530, 420), (560, 320), (580, 230)]
LEG_L = [(290, 690), (250, 780), (230, 830), (265, 905)]          # white leg
LEG_R = [(410, 690), (465, 760), (490, 810), (460, 880)]          # black leg
TORSO = [(300, 400), (240, 470), (228, 580), (250, 680), (330, 725), (420, 715), (470, 640), (468, 520),
         (440, 430), (380, 395), (300, 400)]
SPOTS = [[(220, 600), (300, 560), (330, 620), (300, 700), (360, 740), (200, 760), (200, 600)],
         [(430, 470), (480, 450), (480, 560), (450, 545), (430, 470)]]
TAIL = [(260, 650), (200, 680), (170, 740), (150, 800)]
FRAMES = 8

# typing: sitting on his butt, back legs out in front, a keyboard across his lap
SIT_LEG_L = [(290, 690), (240, 745), (222, 792), (232, 818)]
SIT_LEG_R = [(410, 690), (465, 745), (484, 792), (472, 818)]
KEYBOARD = (196, 700, 504, 800)          # body coordinates: x0, y0, x1, y1
TYPE_FRAMES = [(0, 0), (1, 0), (0, 0), (0, 1), (0, 0), (1, 0), (0, 1), (0, 0)]   # (left up, right up)

# riding: side on, sitting; the back legs go forward to the pedals, the front legs to the handlebars
RIDE_SEAT = (350, 722)                   # body coordinates: the bottom of his butt
RIDE_HIPS = ((330, 680), (380, 685))     # far (white) leg, near (black) leg
RIDE_CRANK, RIDE_PEDAL = (545, 860), 50  # the pedals' middle and how far out they go
THIGH, SHIN = 175, 160
RIDE_ARM_FAR = [(330, 475), (440, 555), (530, 560), (590, 532)]
RIDE_ARM_NEAR = [(440, 470), (520, 548), (575, 545), (622, 518)]
RIDE_FRAMES = 8


def T(p):
    """Body coordinates -> canvas (the body is drawn at K scale around the neck)."""
    return 350 + (p[0] - 350) * K, 405 + (p[1] - 400) * K


def path(cr, pts):
    """Smooth curve through the points (Catmull-Rom)."""
    pts = [T(p) for p in pts]
    cr.move_to(*pts[0])
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        cr.curve_to(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                    p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, *p2)


def limb(cr, pts, fill=(1, 1, 1), hoof=20):
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    path(cr, pts)
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(LIMB + 2 * LW)
    cr.stroke()
    path(cr, pts)
    cr.set_source_rgb(*fill)
    cr.set_line_width(LIMB)
    cr.stroke()
    (x1, y1), (x2, y2) = T(pts[-2]), T(pts[-1])        # hoof: the last bit, black
    d = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / d, (y2 - y1) / d
    cr.move_to(x2 - ux * hoof, y2 - uy * hoof)
    cr.line_to(x2 + ux * 4, y2 + uy * 4)
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(LIMB + 2 * LW + 4)
    cr.set_line_cap(cairo.LINE_CAP_BUTT)
    cr.stroke()
    cr.arc(x2 + ux * 4, y2 + uy * 4, (LIMB + 2 * LW + 4) / 2, 0, 2 * math.pi)
    cr.fill()


def head_surface():
    im = Image.open(SRC / "larry.png").convert("RGBA")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).polygon(HEAD_CUT, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    r, g, b, a = im.split()
    prem = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a))
    data = bytearray(prem.tobytes())
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, im.width, im.height, im.width * 4), data


def waddle(leg, sway, bend):
    """A leg moved for one waddle frame: swung by `sway` radians around its top joint (hip or
    shoulder), then bent by `bend` radians at the knee/elbow (a positive bend lifts it)."""
    top, *rest = leg
    def rot(p, c, a):
        dx, dy = p[0] - c[0], p[1] - c[1]
        return c[0] + dx * math.cos(a) - dy * math.sin(a), c[1] + dx * math.sin(a) + dy * math.cos(a)
    pts = [top] + [rot(p, top, sway) for p in rest]
    side = 1 if leg[-1][0] > leg[0][0] else -1        # which way this leg points (bend it inwards)
    joint = pts[2]
    pts[3] = rot(pts[3], joint, -side * bend)
    pts[2] = rot(pts[2], pts[1], -side * bend * 0.35)
    return pts


def render(legs=(LEG_L, LEG_R), arms=(ARM_L, ARM_R)):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 1000)
    cr = cairo.Context(surf)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    path(cr, TAIL)
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(12)
    cr.stroke()
    x, y = T((150, 795))
    for a in (-0.5, 0, 0.5):   # tuft
        cr.move_to(x, y)
        cr.line_to(x + math.sin(a) * 24, y + math.cos(a) * 28)
        cr.set_line_width(13)
        cr.stroke()
    limb(cr, legs[0])
    limb(cr, legs[1], fill=(0.03, 0.03, 0.03))
    limb(cr, arms[0])
    limb(cr, arms[1])
    path(cr, TORSO)
    cr.close_path()
    cr.set_source_rgb(1, 1, 1)
    cr.fill_preserve()
    cr.save()
    cr.clip()
    cr.set_source_rgb(0, 0, 0)
    for spot in SPOTS:
        path(cr, spot)
        cr.close_path()
        cr.fill()
    cr.restore()
    path(cr, TORSO)
    cr.close_path()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(LW)
    cr.stroke()
    hs, _keep = head_surface()
    cr.set_source_surface(hs, *HEAD_AT)
    cr.paint()
    surf.flush()
    return Image.frombuffer("RGBA", (700, 1000), bytes(surf.get_data()), "raw", "BGRa", surf.get_stride(), 1)


def keyboard(cr):
    """A little keyboard: dark body, rows of light keys, a space bar, thick outline."""
    x0, y0 = T(KEYBOARD[:2])
    x1, y1 = T(KEYBOARD[2:])
    def rrect(x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
    rrect(x0, y0, x1 - x0, y1 - y0, 12)
    cr.set_source_rgb(0.22, 0.23, 0.26)
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(LW)
    cr.stroke()
    cols, rows = 10, 3
    kw = (x1 - x0 - 24) / cols
    kh = (y1 - y0 - 18) / (rows + 1)
    for r in range(rows):
        for c in range(cols):
            rrect(x0 + 12 + c * kw + 2, y0 + 9 + r * kh + 2, kw - 4, kh - 4, 3)
            cr.set_source_rgb(0.86, 0.87, 0.9)
            cr.fill()
    rrect(x0 + 12 + 2.5 * kw, y0 + 9 + rows * kh + 2, 5 * kw, kh - 4, 3)    # space bar
    cr.set_source_rgb(0.86, 0.87, 0.9)
    cr.fill()


def typing_arm(shoulder, side, up):
    """A front leg bent down onto the keyboard; up = this hoof is lifted mid-tap."""
    sx, sy = shoulder
    elbow = (sx + side * 70, sy + 95 - up * 12)
    hoof = (sx + side * 10, 712 - up * 30)        # resting on the top row of keys
    mid = ((elbow[0] + hoof[0]) / 2 + side * 6, (elbow[1] + hoof[1]) / 2)
    return [shoulder, elbow, mid, hoof]


def render_typing(left_up, right_up):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 1000)
    cr = cairo.Context(surf)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    path(cr, [(250, 690), (190, 730), (150, 770), (120, 790)])   # tail, lying on the ground
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(12)
    cr.stroke()
    x, y = T((120, 790))
    for a in (-0.4, 0.1, 0.6):
        cr.move_to(x, y)
        cr.line_to(x - math.cos(a) * 26, y + math.sin(a) * 20)
        cr.set_line_width(13)
        cr.stroke()
    limb(cr, SIT_LEG_L)
    limb(cr, SIT_LEG_R, fill=(0.03, 0.03, 0.03))
    path(cr, TORSO)
    cr.close_path()
    cr.set_source_rgb(1, 1, 1)
    cr.fill_preserve()
    cr.save()
    cr.clip()
    cr.set_source_rgb(0, 0, 0)
    for spot in SPOTS:
        path(cr, spot)
        cr.close_path()
        cr.fill()
    cr.restore()
    path(cr, TORSO)
    cr.close_path()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(LW)
    cr.stroke()
    keyboard(cr)
    limb(cr, typing_arm((270, 470), -1, left_up))
    limb(cr, typing_arm((440, 470), 1, right_up))
    hs, _keep = head_surface()
    cr.set_source_surface(hs, HEAD_AT[0], HEAD_AT[1] + 6)   # head bent down a touch, looking at the keys
    cr.paint()
    surf.flush()
    return Image.frombuffer("RGBA", (700, 1000), bytes(surf.get_data()), "raw", "BGRa", surf.get_stride(), 1)


def bent_leg(hip, foot):
    """Hip to foot with the knee bent forward and up (two equal-ish segments, like a pedalling leg)."""
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    d = min(math.hypot(dx, dy), THIGH + SHIN - 1)
    a = math.atan2(dy, dx)
    k = math.acos(max(-1, min(1, (THIGH ** 2 + d ** 2 - SHIN ** 2) / (2 * THIGH * d))))
    knee = (hip[0] + THIGH * math.cos(a - k), hip[1] + THIGH * math.sin(a - k))   # the forward/up side
    mid = (knee[0] + (foot[0] - knee[0]) * 0.55, knee[1] + (foot[1] - knee[1]) * 0.55)
    return [hip, knee, mid, foot]


def render_riding(angle):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 1000)
    cr = cairo.Context(surf)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    path(cr, [(250, 680), (200, 700), (170, 740), (160, 790)])   # tail hanging off the back
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(12)
    cr.stroke()
    x, y = T((160, 790))
    for a in (-0.5, 0, 0.5):
        cr.move_to(x, y)
        cr.line_to(x + math.sin(a) * 24, y + math.cos(a) * 28)
        cr.set_line_width(13)
        cr.stroke()
    cx, cy = RIDE_CRANK
    far = (cx - math.cos(angle) * RIDE_PEDAL, cy - math.sin(angle) * RIDE_PEDAL)
    near = (cx + math.cos(angle) * RIDE_PEDAL, cy + math.sin(angle) * RIDE_PEDAL)
    limb(cr, bent_leg(RIDE_HIPS[0], far))                          # far side: behind him
    limb(cr, RIDE_ARM_FAR)
    path(cr, TORSO)
    cr.close_path()
    cr.set_source_rgb(1, 1, 1)
    cr.fill_preserve()
    cr.save()
    cr.clip()
    cr.set_source_rgb(0, 0, 0)
    for spot in SPOTS:
        path(cr, spot)
        cr.close_path()
        cr.fill()
    cr.restore()
    path(cr, TORSO)
    cr.close_path()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(LW)
    cr.stroke()
    limb(cr, bent_leg(RIDE_HIPS[1], near), fill=(0.03, 0.03, 0.03))   # near side: in front
    limb(cr, RIDE_ARM_NEAR)
    hs, _keep = head_surface()
    cr.set_source_surface(hs, *HEAD_AT)
    cr.paint()
    surf.flush()
    return Image.frombuffer("RGBA", (800, 1000), bytes(surf.get_data()), "raw", "BGRa", surf.get_stride(), 1)


def standing_box():
    """Where Larry's standing picture (as the pet sprite crops it) would sit on the canvas: his head
    is copied from it unscaled at HEAD_AT, so accessories fitted to it can go on these poses too."""
    x0, y0, x1, y1 = Image.open(SRC / "larry.png").getchannel("A").getbbox()
    return x0 + HEAD_AT[0], y0 + HEAD_AT[1], x1 + HEAD_AT[0], y1 + HEAD_AT[1]


def save_sheet(frames, name, out, fall_box, points=None, lengths=None, rects=None):
    boxes = [f.getchannel("A").getbbox() for f in frames]
    box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    fw, fh = box[2] - box[0], box[3] - box[1]
    sheet = Image.new("RGBA", (fw * len(frames), fh), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f.crop(box), (i * fw, 0))
    sheet.save(out / f"{name}.png")
    meta = {"frames": len(frames), "frame_w": fw, "frame_h": fh,
            "scale": round(1.625 * fh / (fall_box[3] - fall_box[1]), 4)}
    for key, p in (points or {}).items():    # body points as fractions of the frame
        x, y = T(p)
        meta[key] = [round((x - box[0]) / fw, 4), round((y - box[1]) / fh, 4)]
    for key, d in (lengths or {}).items():   # body lengths as fractions of the frame's height
        meta[key] = round(d * K / fh, 4)
    for key, (x0, y0, x1, y1) in (rects or {}).items():   # canvas rectangles as fractions of the frame
        meta[key] = [round((x0 - box[0]) / fw, 4), round((y0 - box[1]) / fh, 4),
                     round((x1 - box[0]) / fw, 4), round((y1 - box[1]) / fh, 4)]
    (out / f"{name}.json").write_text(json.dumps(meta))
    return fw, fh


def main(out=SRC):
    falling = render()
    fall_box = falling.getchannel("A").getbbox()
    falling.crop(fall_box).save(out / "larry-falling.png")
    frames = []
    for i in range(FRAMES):
        ph = 2 * math.pi * i / FRAMES
        sway = 0.16 * math.sin(ph)                     # everything rocks side to side together
        lift_l = 0.55 * max(0, math.sin(ph))           # then the legs take turns lifting...
        lift_r = 0.55 * max(0, -math.sin(ph))
        frames.append(render(
            (waddle(LEG_L, sway, lift_l), waddle(LEG_R, sway, lift_r)),
            # ...and each front leg pumps when the back leg on the other side lifts
            (waddle(ARM_L, -sway * 1.4, 0.7 * lift_r), waddle(ARM_R, -sway * 1.4, 0.7 * lift_l))))
    # one crop for every frame (and the falling pose) so nothing jumps between them
    boxes = [f.getchannel("A").getbbox() for f in frames] + [fall_box]
    box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    fw, fh = box[2] - box[0], box[3] - box[1]
    sheet = Image.new("RGBA", (fw * FRAMES, fh), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f.crop(box), (i * fw, 0))
    sheet.save(out / "larry-held.png")
    # same scale as the falling pose: its height (767 px) is 1.625x Larry's standing height
    (out / "larry-held.json").write_text(json.dumps({
        "frames": FRAMES, "frame_w": fw, "frame_h": fh,
        "scale": round(1.625 * fh / (fall_box[3] - fall_box[1]), 4)}))
    tw, th = save_sheet([render_typing(*f) for f in TYPE_FRAMES], "larry-typing", out, fall_box)
    rw, rh = save_sheet([render_riding(2 * math.pi * i / RIDE_FRAMES) for i in range(RIDE_FRAMES)],
                        "larry-riding", out, fall_box, {"seat": RIDE_SEAT, "crank": RIDE_CRANK},
                        {"pedal": RIDE_PEDAL}, {"pet_box": standing_box()})
    print(f"falling {fall_box[2] - fall_box[0]}x{fall_box[3] - fall_box[1]}, held {FRAMES} frames of {fw}x{fh}, "
          f"typing {len(TYPE_FRAMES)} frames of {tw}x{th}, riding {RIDE_FRAMES} frames of {rw}x{rh}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else SRC)
