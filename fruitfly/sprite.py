"""Cairo-drawn housefly sprite (top-down view, drawn along +x heading)."""

from __future__ import annotations

import math

BODY = (0.16, 0.12, 0.08)       # dark brown
THORAX = (0.24, 0.18, 0.10)
EYE = (0.45, 0.08, 0.05)        # dark red
WING = (0.75, 0.78, 0.85, 0.35)  # translucent bluish
LEG = (0.10, 0.08, 0.05)


def draw_fly(cr, x: float, y: float, heading: float, size: float,
             flying: bool, wing_phase: float, escaping: bool = False) -> None:
    cr.save()
    cr.translate(x, y)
    cr.rotate(heading)
    s = size / 34.0

    # faint drop shadow when landed (sitting on the "glass")
    if not flying:
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.save()
        cr.translate(2 * s, 3 * s)
        cr.scale(1.1, 0.9)
        _ellipse(cr, 0, 0, 12 * s, 7 * s)
        cr.fill()
        cr.restore()

    # legs
    cr.set_line_width(max(1.0, 1.2 * s))
    cr.set_source_rgb(*LEG)
    if flying:
        # legs tucked: two short trailing strokes
        for sy in (-1, 1):
            cr.move_to(-2 * s, 3 * s * sy)
            cr.line_to(-9 * s, 5 * s * sy)
            cr.stroke()
    else:
        for i, ang in enumerate((-0.9, -0.35, 0.35, 0.9, 2.2, -2.2)):
            lx = math.cos(ang) * 12 * s
            ly = math.sin(ang) * 10 * s
            cr.move_to(0, 0)
            cr.curve_to(lx * 0.5, ly * 0.7, lx * 0.8, ly, lx, ly)
            cr.stroke()

    # wings
    if flying:
        # 200 Hz flapping reads as a blur: two wing arcs at sampled angles
        for sy in (-1, 1):
            flap = 0.55 + 0.5 * math.sin(wing_phase + (0 if sy < 0 else math.pi))
            for a, alpha in ((flap, WING[3]), (flap * 0.55, WING[3] * 0.5)):
                cr.save()
                cr.translate(1 * s, 0)
                cr.rotate(sy * (0.5 + a * 0.9))
                cr.scale(1.0, 0.42)
                cr.set_source_rgba(WING[0], WING[1], WING[2], alpha)
                _ellipse(cr, -11 * s, 0, 11 * s, 5.2 * s)
                cr.fill()
                cr.restore()
    else:
        # wings folded flat over the abdomen
        for sy in (-1, 1):
            cr.save()
            cr.translate(-2 * s, 0)
            cr.rotate(sy * 0.16)
            cr.scale(1.0, 0.35)
            cr.set_source_rgba(WING[0], WING[1], WING[2], 0.45)
            _ellipse(cr, -8 * s, sy * 2.4 * s, 9.5 * s, 4.6 * s)
            cr.fill()
            cr.restore()

    # abdomen (striped)
    cr.set_source_rgb(*BODY)
    cr.save()
    cr.scale(1.35, 1.0)
    _ellipse(cr, -6.5 * s, 0, 6.2 * s, 4.6 * s)
    cr.fill()
    cr.restore()
    cr.set_source_rgba(0, 0, 0, 0.35)
    cr.set_line_width(1.0 * s)
    for i in range(3):
        bx = (-4.5 - i * 2.6) * s
        cr.move_to(bx, -3.6 * s)
        cr.curve_to(bx - 1.2 * s, 0, bx - 1.2 * s, 0, bx, 3.6 * s)
        cr.stroke()

    # thorax
    cr.set_source_rgb(*THORAX)
    _ellipse(cr, 1.5 * s, 0, 5.0 * s, 4.2 * s)
    cr.fill()

    # head + eyes
    cr.set_source_rgb(*BODY)
    _ellipse(cr, 7.5 * s, 0, 3.0 * s, 3.2 * s)
    cr.fill()
    eye = (0.75, 0.15, 0.10) if escaping else EYE
    for sy in (-1, 1):
        cr.set_source_rgb(*eye)
        _ellipse(cr, 8.6 * s, sy * 1.7 * s, 1.7 * s, 1.5 * s)
        cr.fill()

    cr.restore()


def _ellipse(cr, cx, cy, rx, ry):
    cr.save()
    cr.translate(cx, cy)
    cr.scale(rx, ry)
    cr.arc(0, 0, 1.0, 0, 2 * math.pi)
    cr.restore()
