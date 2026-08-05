import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type GraphViewNode = { id: string; title: string; color: string };
export type GraphViewLink = { source: string; target: string };

type Sim = {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** degree, used for node radius -- hubs read as bigger, like Obsidian */
  deg: number;
  fixed: boolean;
};

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 4;
/** Labels below this zoom would be unreadable mush, so they fade out. */
const LABEL_MIN_ZOOM = 0.55;
/** Caps how far a node can move per frame, so a repulsion spike moves it fast
 *  instead of flinging it across the screen. */
const MAX_SPEED = 8;
/** Shared by the tick loop and the JSX render so the two can't drift apart. */
function radiusFor(deg: number, emphasised: boolean): number {
  return 3.5 + Math.min(Math.sqrt(deg) * 1.2, 6) + (emphasised ? 2 : 0);
}

export function GraphView({
  nodes,
  links,
  onSelect,
  selectedId,
  footerNote,
}: {
  nodes: GraphViewNode[];
  links: GraphViewLink[];
  onSelect: (id: string) => void;
  selectedId?: string | null;
  footerNote?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const groupRef = useRef<SVGGElement>(null);
  const [size, setSize] = useState({ w: 900, h: 560 });
  const [hover, setHover] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  // Cursor style only, set once per pan gesture rather than per move.
  const [isPanning, setIsPanning] = useState(false);
  // Bumped once per (re)seed so the DOM nodes exist for the refs below --
  // not per physics frame, that's handled by direct attribute writes.
  const [, setSeedVersion] = useState(0);

  const edges = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    return links
      .filter((l) => ids.has(l.source) && ids.has(l.target))
      .map((l) => [l.source, l.target] as [string, string]);
  }, [nodes, links]);

  /** Adjacency, for Obsidian-style neighbour highlighting on hover. */
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const n of nodes) map.set(n.id, new Set());
    for (const [s, t] of edges) {
      map.get(s)?.add(t);
      map.get(t)?.add(s);
    }
    return map;
  }, [nodes, edges]);

  const simRef = useRef<Sim[]>([]);
  const indexRef = useRef<Map<string, number>>(new Map());
  const alphaRef = useRef(1);
  const dragRef = useRef<{ id: string; moved: boolean } | null>(null);
  // start*/base*: pointer position and view.x/y when the pan began. cur*: the
  // live pan position, committed to `view` once on pointer-up.
  const panRef = useRef<{
    startX: number;
    startY: number;
    baseX: number;
    baseY: number;
    curX: number;
    curY: number;
  } | null>(null);

  // Direct-DOM handles for the per-frame hot path -- physics/pan write here
  // instead of calling setState.
  const nodeElsRef = useRef<Map<string, SVGGElement>>(new Map());
  const edgeElsRef = useRef<Map<string, SVGLineElement>>(new Map());

  // Reseed on graph change, not on resize (so resizing keeps the layout).
  useEffect(() => {
    const n = nodes.length;
    const deg = new Map<string, number>();
    for (const [s, t] of edges) {
      deg.set(s, (deg.get(s) ?? 0) + 1);
      deg.set(t, (deg.get(t) ?? 0) + 1);
    }
    simRef.current = nodes.map((node, i) => ({
      id: node.id,
      // Small jitter off the perfect circle -- kept small so adjacent nodes
      // can't land near-coincident and spike repulsion (1/d^2).
      x: Math.cos((i / n) * Math.PI * 2) * 240 + (Math.random() - 0.5) * 12,
      y: Math.sin((i / n) * Math.PI * 2) * 240 + (Math.random() - 0.5) * 12,
      vx: 0,
      vy: 0,
      deg: deg.get(node.id) ?? 0,
      fixed: false,
    }));
    indexRef.current = new Map(simRef.current.map((p, i) => [p.id, i]));
    alphaRef.current = 1;
    nodeElsRef.current.clear();
    edgeElsRef.current.clear();
    setSeedVersion((v) => v + 1);
  }, [nodes, edges]);

  // Force simulation: runs in rAF while it has energy, writes positions
  // straight to the DOM via the refs above -- no per-frame setState.
  useEffect(() => {
    let raf = 0;
    const step = () => {
      const pts = simRef.current;
      const index = indexRef.current;
      const alpha = alphaRef.current;
      const dragging = dragRef.current !== null;

      if (alpha > 0.005 || dragging) {
        const target = 90;
        // Floored at 100 (min separation 10) so near-coincident seed points
        // can't spike into a near-infinite force.
        const MIN_D2 = 100;
        for (let i = 0; i < pts.length; i++) {
          for (let j = i + 1; j < pts.length; j++) {
            const a = pts[i]!;
            const b = pts[j]!;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const d2 = Math.max(dx * dx + dy * dy, MIN_D2);
            const d = Math.sqrt(d2);
            const f = (target * target) / d2;
            const fx = (dx / d) * f;
            const fy = (dy / d) * f;
            a.vx -= fx;
            a.vy -= fy;
            b.vx += fx;
            b.vy += fy;
          }
        }
        for (const [s, t] of edges) {
          const a = pts[index.get(s)!];
          const b = pts[index.get(t)!];
          if (!a || !b) continue;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const d = Math.hypot(dx, dy) || 0.01;
          const f = (d - target) * 0.06;
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          a.vx += fx;
          a.vy += fy;
          b.vx -= fx;
          b.vy -= fy;
        }
        for (const p of pts) {
          if (p.fixed) {
            p.vx = 0;
            p.vy = 0;
          } else {
            p.vx += -p.x * 0.012; // pull toward the origin
            p.vy += -p.y * 0.012;
            const speed = Math.hypot(p.vx, p.vy); // clamp to MAX_SPEED
            if (speed > MAX_SPEED) {
              const s = MAX_SPEED / speed;
              p.vx *= s;
              p.vy *= s;
            }
            p.x += p.vx * Math.max(alpha, 0.12);
            p.y += p.vy * Math.max(alpha, 0.12);
            p.vx *= 0.62;
            p.vy *= 0.62;
          }
          // Direct DOM write: move this node's group. No React re-render.
          const el = nodeElsRef.current.get(p.id);
          if (el) el.setAttribute("transform", `translate(${p.x} ${p.y})`);
        }
        for (const [s, t] of edges) {
          const line = edgeElsRef.current.get(`${s}|${t}`);
          if (!line) continue;
          const a = pts[index.get(s)!];
          const b = pts[index.get(t)!];
          if (!a || !b) continue;
          line.setAttribute("x1", String(a.x));
          line.setAttribute("y1", String(a.y));
          line.setAttribute("x2", String(b.x));
          line.setAttribute("y2", String(b.y));
        }
        alphaRef.current = dragging ? Math.max(alpha, 0.3) : alpha * 0.97;
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [edges]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setSize({
        w: Math.max(entry.contentRect.width, 320),
        h: Math.max(entry.contentRect.height, 420),
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const applyGroupTransform = (x: number, y: number, k: number) => {
    groupRef.current?.setAttribute(
      "transform",
      `translate(${size.w / 2 + x} ${size.h / 2 + y}) scale(${k})`,
    );
  };

  /** Screen point -> graph coordinates. Reads the live pan from panRef during
   *  an active pan, falls back to `view` otherwise. */
  const toGraph = useCallback(
    (clientX: number, clientY: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      const pan = panRef.current;
      const vx = pan ? pan.curX : view.x;
      const vy = pan ? pan.curY : view.y;
      return {
        x: (clientX - rect.left - size.w / 2 - vx) / view.k,
        y: (clientY - rect.top - size.h / 2 - vy) / view.k,
      };
    },
    [size.w, size.h, view],
  );

  // Wheel zoom, anchored on the cursor so the point under the pointer stays
  // put. Wheel events are naturally throttled by the browser/trackpad, so this
  // stays on React state -- it isn't the source of frame drops.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const px = e.clientX - rect.left - size.w / 2;
      const py = e.clientY - rect.top - size.h / 2;
      setView((v) => {
        const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * Math.exp(-e.deltaY * 0.0015)));
        const ratio = k / v.k;
        return { k, x: px - (px - v.x) * ratio, y: py - (py - v.y) * ratio };
      });
    };
    // passive:false so preventDefault actually stops the page from scrolling.
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [size.w, size.h]);

  const onNodePointerDown = (e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const p = simRef.current[indexRef.current.get(id)!];
    if (p) p.fixed = true;
    dragRef.current = { id, moved: false };
    alphaRef.current = Math.max(alphaRef.current, 0.3);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (drag) {
      const g = toGraph(e.clientX, e.clientY);
      const p = simRef.current[indexRef.current.get(drag.id)!];
      if (p) {
        p.x = g.x;
        p.y = g.y;
        drag.moved = true;
      }
      return;
    }
    const pan = panRef.current;
    if (pan) {
      // Move the group directly every event, commit to state only on pan end
      // -- a fast trackpad pan fires well over 60 events/sec.
      pan.curX = pan.baseX + (e.clientX - pan.startX);
      pan.curY = pan.baseY + (e.clientY - pan.startY);
      applyGroupTransform(pan.curX, pan.curY, view.k);
    }
  };

  const endDrag = () => {
    const drag = dragRef.current;
    if (drag) {
      const p = simRef.current[indexRef.current.get(drag.id)!];
      if (p) p.fixed = false; // release back to the simulation
      // A click that never moved is a selection, not a drag.
      if (!drag.moved) onSelect(drag.id);
      dragRef.current = null;
      alphaRef.current = Math.max(alphaRef.current, 0.2);
    }
    const pan = panRef.current;
    if (pan) {
      // Commit the final pan position now that the fast path is done.
      setView((v) => ({ ...v, x: pan.curX, y: pan.curY }));
      panRef.current = null;
      setIsPanning(false);
    }
  };

  const onBackgroundPointerDown = (e: React.PointerEvent) => {
    panRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      baseX: view.x,
      baseY: view.y,
      curX: view.x,
      curY: view.y,
    };
    setIsPanning(true);
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  };

  const resetView = () => {
    setView({ x: 0, y: 0, k: 1 });
    applyGroupTransform(0, 0, 1);
  };

  const pts = simRef.current;
  const byId = new Map(pts.map((p) => [p.id, p]));
  const active = hover ?? selectedId ?? null;
  const activeSet = active ? neighbours.get(active) : undefined;
  const showLabels = view.k >= LABEL_MIN_ZOOM;

  const isDimmed = (id: string) =>
    active !== null && id !== active && !(activeSet?.has(id) ?? false);

  return (
    <div
      ref={containerRef}
      className="relative h-full min-h-[420px] w-full overflow-hidden rounded-xl border border-border bg-background"
    >
      <svg
        ref={svgRef}
        width={size.w}
        height={size.h}
        className="block touch-none select-none"
        style={{ cursor: isPanning ? "grabbing" : "grab" }}
        onPointerDown={onBackgroundPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
      >
        <g
          ref={groupRef}
          transform={`translate(${size.w / 2 + view.x} ${size.h / 2 + view.y}) scale(${view.k})`}
        >
          {edges.map(([s, t]) => {
            const a = byId.get(s);
            const b = byId.get(t);
            if (!a || !b) return null;
            const lit = active === s || active === t;
            const dim = active !== null && !lit;
            return (
              <line
                key={`${s}-${t}`}
                ref={(el) => {
                  if (el) edgeElsRef.current.set(`${s}|${t}`, el);
                  else edgeElsRef.current.delete(`${s}|${t}`);
                }}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={lit ? "#A855C7" : "#591E82"}
                strokeOpacity={dim ? 0.08 : lit ? 0.9 : 0.35}
                strokeWidth={(lit ? 1.6 : 1) / view.k}
              />
            );
          })}

          {nodes.map((node) => {
            const p = byId.get(node.id);
            if (!p) return null;
            const isHover = hover === node.id;
            const isSelected = selectedId === node.id;
            const dim = isDimmed(node.id);
            const r = radiusFor(p.deg, isHover || isSelected);
            return (
              <g
                key={node.id}
                ref={(el) => {
                  if (el) nodeElsRef.current.set(node.id, el);
                  else nodeElsRef.current.delete(node.id);
                }}
                transform={`translate(${p.x} ${p.y})`}
                opacity={dim ? 0.25 : 1}
                onPointerDown={(e) => onNodePointerDown(e, node.id)}
                onPointerEnter={() => setHover(node.id)}
                onPointerLeave={() => setHover(null)}
                className="cursor-pointer"
              >
                <circle
                  cx={0}
                  cy={0}
                  r={r}
                  fill={node.color}
                  stroke={isSelected ? "#FFFFFF" : isHover ? "#FFFFFF" : "#0B0B0B"}
                  strokeOpacity={isSelected || isHover ? 0.95 : 0.5}
                  strokeWidth={(isSelected ? 2.5 : 1.5) / view.k}
                />
                {showLabels && (
                  <text
                    x={0}
                    y={r + 11 / view.k}
                    textAnchor="middle"
                    // Counter-scaled so labels keep a constant on-screen size
                    // however far you zoom in or out.
                    fontSize={11 / view.k}
                    fill={isHover || isSelected ? "#FFFFFF" : "#B6AECB"}
                    className="pointer-events-none"
                    style={{ paintOrder: "stroke", stroke: "#0B0B0B", strokeWidth: 3 / view.k }}
                  >
                    {node.title.length > 34 ? `${node.title.slice(0, 33)}…` : node.title}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      <div className="pointer-events-none absolute top-3 right-3 flex items-center gap-2">
        <button
          onClick={resetView}
          className="pointer-events-auto rounded-md border border-border bg-surface/90 px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          Reset view
        </button>
        <span className="rounded-md bg-surface/70 px-2 py-1 font-mono text-xs text-muted-foreground">
          {Math.round(view.k * 100)}%
        </span>
      </div>

      <div className="pointer-events-none absolute bottom-3 left-4 text-xs text-muted-foreground">
        {footerNote ??
          `${nodes.length} notes · ${edges.length} links · scroll to zoom, drag to pan, drag a node to move it`}
      </div>
    </div>
  );
}
