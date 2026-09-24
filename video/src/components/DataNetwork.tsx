import React, {useMemo} from 'react';
import {C, F} from '../config/theme';
import {BEAT} from '../config/timing';
import type {Layout} from '../config/layout';
import {CENTER, CROSS, Group, OUTER_COUNT, OUTER_LABELS, PRIMARY} from '../data/network';
import {E, clamp, lerp, prog, rng} from '../lib/anim';
import {ScientificNode} from './ScientificNode';
import {typed} from './KineticText';

type P = {x: number; y: number};
type Outer = P & {label?: string; group: Group; parent: number; seed: number; appear: number};

/** Deterministic layout: primaries on an ellipse, context nodes by seeded rejection sampling. */
export const buildNetwork = (L: Layout) => {
  const {w, h, cx, cy, u, vertical} = L;
  const rx = (vertical ? 0.42 : 0.355) * w;
  const ry = (vertical ? 0.3 : 0.37) * h;
  const primary = PRIMARY.map((n) => {
    const a = (n.angle * Math.PI) / 180;
    return {x: cx + Math.cos(a) * n.r * rx, y: cy + Math.sin(a) * n.r * ry};
  });
  const R = rng(1908);
  const outer: Outer[] = [];
  const ok = (p: P, min: number) =>
    [...primary, ...outer, {x: cx, y: cy}].every((q) => Math.hypot(q.x - p.x, q.y - p.y) > min) &&
    p.x > 0.04 * w && p.x < 0.96 * w && p.y > 0.07 * h && p.y < 0.86 * h;
  OUTER_LABELS.forEach((lab, j) => {
    const pi = PRIMARY.findIndex((n) => n.id === lab.near);
    const base = PRIMARY[pi];
    for (let tries = 0; tries < 400; tries++) {
      const a = ((base.angle + (R() - 0.5) * 60) * Math.PI) / 180;
      const r = base.r + 0.2 + R() * 0.3;
      const p = {x: cx + Math.cos(a) * r * rx, y: cy + Math.sin(a) * r * ry};
      if (ok(p, 95 * u) || tries === 399) {
        outer.push({...p, label: lab.text, group: lab.group, parent: pi, seed: R() * 100, appear: 0});
        break;
      }
    }
  });
  while (outer.length < OUTER_COUNT) {
    const a = R() * Math.PI * 2;
    const r = 0.45 + R() * 0.75;
    const p = {x: cx + Math.cos(a) * r * rx, y: cy + Math.sin(a) * r * ry};
    if (!ok(p, 70 * u)) continue;
    let best = 0;
    primary.forEach((q, i) => {
      if (Math.hypot(q.x - p.x, q.y - p.y) < Math.hypot(primary[best].x - p.x, primary[best].y - p.y)) best = i;
    });
    outer.push({...p, group: PRIMARY[best].group, parent: best, seed: R() * 100, appear: 0});
  }
  // appearance order: by distance from centre, so the graph grows outward
  const order = outer.map((o, i) => ({i, d: Math.hypot(o.x - cx, o.y - cy)})).sort((a, b) => a.d - b.d);
  order.forEach(({i}, rank) => (outer[i].appear = BEAT.secondaryIn + rank * 0.085));
  // a few context-to-context links
  const links: [number, number][] = [];
  outer.forEach((o, i) => {
    if (i % 3 !== 0) return;
    let best = -1;
    outer.forEach((q, j) => {
      if (j === i) return;
      if (best < 0 || Math.hypot(q.x - o.x, q.y - o.y) < Math.hypot(outer[best].x - o.x, outer[best].y - o.y)) best = j;
    });
    links.push([i, best]);
  });
  const cross = CROSS.map(([a, b]) => [PRIMARY.findIndex((n) => n.id === a), PRIMARY.findIndex((n) => n.id === b)] as [number, number]);
  return {primary, outer, links, cross};
};
export type Net = ReturnType<typeof buildNetwork>;

const groupWeight = (t: number, g: Group) => {
  const w = (a: number, b: number) => Math.min(E.inOut(prog(t, a - 0.3, a + 0.3)), 1 - E.inOut(prog(t, b - 0.3, b + 0.3)));
  if (g === 'company') return w(7.0, 10.8);
  if (g === 'biology') return w(10.8, 12.9);
  return w(12.9, BEAT.converge[0]);
};

/** Camera + motion for time t. Pure; the stream layer also calls it to hand off strands. */
export const netFrame = (net: Net, t: number, L: Layout) => {
  const {cx, cy, u} = L;
  const conv = prog(t, BEAT.converge[0], BEAT.converge[1]);
  const s =
    lerp(0.93, 1.0, E.inOut(prog(t, 7.0, 11.0))) * lerp(1, 1.08, E.inOut(prog(t, 11.0, 13.6))) / lerp(1, 1.08, E.inOut(conv));
  // pan toward the active group's centroid so the camera travels through the graph
  const centroid = (g: Group) => {
    const pts = net.primary.filter((_, i) => PRIMARY[i].group === g);
    return {x: pts.reduce((a, p) => a + p.x, 0) / pts.length, y: pts.reduce((a, p) => a + p.y, 0) / pts.length};
  };
  let px = 0;
  let py = 0;
  (['company', 'biology', 'science'] as Group[]).forEach((g) => {
    const wgt = groupWeight(t, g);
    const c = centroid(g);
    px -= (c.x - cx) * 0.12 * wgt;
    py -= (c.y - cy) * 0.12 * wgt;
  });
  const settle = 1 - E.inOut(conv);
  const place = (p: P, depth: number, seed: number, start: number) => {
    const drift = 5 * u * depth;
    const dx = Math.sin(t * 0.55 + seed) * drift;
    const dy = Math.cos(t * 0.47 + seed * 1.7) * drift;
    const c = E.inOut(prog(t, start, BEAT.converge[1]));
    const bx = lerp(p.x + dx, cx, c);
    const by = lerp(p.y + dy, cy, c);
    return {x: cx + s * depth * (bx - cx) + px * depth * settle, y: cy + s * depth * (by - cy) + py * depth * settle};
  };
  const primary = net.primary.map((p, i) => place(p, 1, i * 13.1, BEAT.converge[0] + 0.25 + (i % 4) * 0.05));
  const outer = net.outer.map((p) => place(p, 1.14, p.seed, BEAT.converge[0]));
  return {primary, outer, center: {x: cx, y: cy}, s, conv};
};

export const DataNetwork: React.FC<{t: number; L: Layout}> = ({t, L}) => {
  const net = useMemo(() => buildNetwork(L), [L.w, L.h]);
  if (t < BEAT.centerNode - 0.05 || t > BEAT.converge[1] + 0.25) return null;
  const {u, cx} = L;
  const f = netFrame(net, t, L);
  const labelsOut = 1 - E.inOut(prog(t, BEAT.converge[0], BEAT.converge[0] + 0.35));
  const ns = {vectorEffect: 'non-scaling-stroke' as const};

  const primaryIn = (i: number) => E.out(prog(t, BEAT.primaryIn + 0.05 + i * 0.03, BEAT.primaryIn + 0.45 + i * 0.03));
  const outerIn = (j: number) => E.out(prog(t, net.outer[j].appear, net.outer[j].appear + 0.4));
  const hi = (g: Group) => groupWeight(t, g);
  const colorFor = (g: Group) => (hi(g) > 0.5 ? C.accent : C.text2);
  const dimFor = (g: Group) => {
    const anyActive = Math.max(hi('company'), hi('biology'), hi('science'));
    return lerp(1, 0.4 + 0.6 * hi(g), anyActive * labelsOut);
  };

  const edge = (a: P, b: P, p: number, color: string, op: number, key: string, width = 1) => {
    if (p <= 0 || op <= 0) return null;
    return <line key={key} x1={a.x} y1={a.y} x2={lerp(a.x, b.x, p)} y2={lerp(a.y, b.y, p)} stroke={color} strokeOpacity={op} strokeWidth={width * u} {...ns} />;
  };
  const pulses: React.ReactNode[] = [];
  const pulse = (from: P, to: P, seed: number, speed: number, op: number, key: string) => {
    if (op <= 0.02) return;
    const q = (((t * speed + seed) % 1) + 1) % 1;
    pulses.push(<circle key={key} cx={lerp(from.x, to.x, q)} cy={lerp(from.y, to.y, q)} r={2.6 * u} fill={C.accent} opacity={op * Math.sin(Math.PI * q)} />);
  };

  const spokesOn = t >= BEAT.streamToEdges[1] - 0.02;
  const decode = (i: number) => prog(t, BEAT.decode + i * 0.07, BEAT.decode + 0.5 + i * 0.07);

  if (spokesOn) PRIMARY.forEach((_, i) => pulse(f.primary[i], f.center, i * 0.37, 0.5, 0.9 * labelsOut, `ps${i}`));
  if (t > BEAT.crossEdges + 0.8) net.cross.forEach(([a, b], i) => pulse(f.primary[a], f.primary[b], i * 0.23, 0.35, 0.7 * labelsOut, `pc${i}`));
  net.outer.forEach((o, j) => {
    if (j % 2 === 0) pulse(f.outer[j], f.primary[o.parent], j * 0.19, 0.3, 0.5 * outerIn(j) * labelsOut, `po${j}`);
  });

  return (
    <svg width={L.w} height={L.h} style={{position: 'absolute'}}>
      {/* edges */}
      {net.outer.map((o, j) => edge(f.primary[o.parent], f.outer[j], outerIn(j), C.borderStrong, 0.9 * dimFor(o.group), `oe${j}`))}
      {net.links.map(([a, b], i) => edge(f.outer[a], f.outer[b], outerIn(Math.max(a, b)), C.border, 0.9, `ol${i}`))}
      {net.cross.map(([a, b], i) => {
        const p = E.inOut(prog(t, BEAT.crossEdges + i * 0.12, BEAT.crossEdges + 0.6 + i * 0.12));
        const g = PRIMARY[a].group;
        const lit = Math.max(hi(PRIMARY[a].group), hi(PRIMARY[b].group));
        return edge(f.primary[a], f.primary[b], p, lit > 0.5 ? C.accent : C.borderStrong, lerp(0.8, 0.55, lit) * dimFor(g), `ce${i}`);
      })}
      {spokesOn && PRIMARY.map((n, i) => edge(f.center, f.primary[i], 1, hi(n.group) > 0.5 ? C.accent : C.borderStrong, hi(n.group) > 0.5 ? 0.6 : 0.9, `sp${i}`))}
      {/* pulses travel inward: the signals underneath feed the move */}
      {pulses}
      {/* context nodes */}
      {net.outer.map((o, j) => {
        const lab = o.label ? typed(o.label, prog(t, BEAT.decode + 0.4 + j * 0.05, BEAT.decode + 0.9 + j * 0.05)) : undefined;
        return (
          <g key={`on${j}`}>
            <circle cx={f.outer[j].x} cy={f.outer[j].y} r={(o.label ? 3.4 : 2.4) * u} fill={o.label ? C.text2 : C.faint} opacity={outerIn(j) * dimFor(o.group)} />
            {lab && (
              <text x={f.outer[j].x + 10 * u} y={f.outer[j].y + 4 * u} fill={o.group === 'biology' ? C.accentSoft : C.muted} fontFamily={F.mono} fontSize={12.5 * u} letterSpacing={0.8 * u} opacity={outerIn(j) * labelsOut * dimFor(o.group) * 0.9}>
                {lab}
              </text>
            )}
          </g>
        );
      })}
      {/* primary entities: TYPE in scene 03, decoded entity in scene 04 */}
      {PRIMARY.map((n, i) => {
        const d = decode(i);
        const p = f.primary[i];
        const side = p.x > L.w - 430 * u ? 'left' : p.x < 430 * u ? 'right' : p.x >= cx ? 'right' : 'left';
        const title = d <= 0 ? n.type : typed(n.name, E.soft(d));
        const tag = d <= 0 ? undefined : typed(`${n.type} · ${n.tag}`, E.soft(clamp(d * 1.4)));
        return (
          <ScientificNode
            key={n.id} x={p.x} y={p.y} u={u} shape={n.shape} color={colorFor(n.group)} opacity={primaryIn(i) * dimFor(n.group)}
            scale={lerp(0.6, 1, primaryIn(i)) * lerp(1, 0.5, E.in(prog(t, BEAT.converge[0] + 0.25, BEAT.converge[1])))}
            title={title} titleMono={d <= 0} tag={tag} side={side} labelOpacity={labelsOut} glow={hi(n.group)}
          />
        );
      })}
      {/* the company at the centre of it all */}
      <ScientificNode
        x={f.center.x} y={f.center.y} u={u} shape="core" color={C.text} scale={lerp(0.4, 1, E.overshoot(prog(t, BEAT.centerNode, BEAT.centerNode + 0.5)))}
        opacity={E.out(prog(t, BEAT.centerNode - 0.05, BEAT.centerNode + 0.2))} title={CENTER.name} tag={t > BEAT.decode ? CENTER.tag : CENTER.type}
        side="right" labelOpacity={labelsOut} glow={prog(t, BEAT.converge[1] - 0.5, BEAT.converge[1])}
      />
    </svg>
  );
};
