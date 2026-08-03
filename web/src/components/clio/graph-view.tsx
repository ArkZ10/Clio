import { useEffect, useMemo, useRef, useState } from "react";
import { paperNotes } from "@/lib/clio-data";

const CLUSTER_FILL = ["#7A29A3", "#591E82", "#3D155D"];

type Point = { id: string; x: number; y: number };

function computeLayout(width: number, height: number, edges: [string, string][]): Point[] {
  const n = paperNotes.length;
  const pts = paperNotes.map((note, i) => ({
    id: note.id,
    x: width / 2 + Math.cos((i / n) * Math.PI * 2) * Math.min(width, height) * 0.32,
    y: height / 2 + Math.sin((i / n) * Math.PI * 2) * Math.min(width, height) * 0.32,
    vx: 0,
    vy: 0,
  }));
  const index = new Map(pts.map((p, i) => [p.id, i]));
  const target = Math.min(width, height) / 4.5;

  for (let step = 0; step < 400; step++) {
    const alpha = 1 - step / 400;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const a = pts[i]!;
        const b = pts[j]!;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.hypot(dx, dy) || 0.01;
        const f = (target * target * 1.1) / (d * d);
        a.vx -= (dx / d) * f;
        a.vy -= (dy / d) * f;
        b.vx += (dx / d) * f;
        b.vy += (dy / d) * f;
      }
    }
    for (const [s, t] of edges) {
      const a = pts[index.get(s)!];
      const b = pts[index.get(t)!];
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = (d - target) * 0.08;
      a.vx += (dx / d) * f;
      a.vy += (dy / d) * f;
      b.vx -= (dx / d) * f;
      b.vy -= (dy / d) * f;
    }
    for (const p of pts) {
      p.vx += (width / 2 - p.x) * 0.02;
      p.vy += (height / 2 - p.y) * 0.02;
      p.x = Math.min(width - 44, Math.max(44, p.x + p.vx * alpha));
      p.y = Math.min(height - 44, Math.max(44, p.y + p.vy * alpha));
      p.vx *= 0.6;
      p.vy *= 0.6;
    }
  }

  return pts.map(({ id, x, y }) => ({ id, x, y }));
}

export function GraphView({ onSelect }: { onSelect: (id: string) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 560 });
  const [hover, setHover] = useState<string | null>(null);

  const edges = useMemo(() => {
    const seen = new Set<string>();
    const list: [string, string][] = [];
    for (const n of paperNotes) {
      for (const t of n.linked) {
        const key = [n.id, t].sort().join("|");
        if (!seen.has(key) && paperNotes.some((p) => p.id === t)) {
          seen.add(key);
          list.push([n.id, t]);
        }
      }
    }
    return list;
  }, []);

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

  const points = useMemo(() => computeLayout(size.w, size.h, edges), [size.w, size.h, edges]);
  const byId = useMemo(() => new Map(points.map((p) => [p.id, p])), [points]);
  const hovered = hover ? byId.get(hover) : null;

  return (
    <div
      ref={containerRef}
      className="relative h-full min-h-[420px] w-full overflow-hidden rounded-xl border border-border bg-background"
    >
      <svg width={size.w} height={size.h} className="block">
        {edges.map(([s, t]) => {
          const a = byId.get(s);
          const b = byId.get(t);
          if (!a || !b) return null;
          const active = hover === s || hover === t;
          return (
            <line
              key={`${s}-${t}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={active ? "#7A29A3" : "#591E82"}
              strokeOpacity={active ? 0.9 : 0.5}
              strokeWidth={active ? 1.6 : 1}
            />
          );
        })}
        {paperNotes.map((note) => {
          const p = byId.get(note.id);
          if (!p) return null;
          const active = hover === note.id;
          return (
            <g key={note.id}>
              <circle
                cx={p.x}
                cy={p.y}
                r={active ? 13 : 10}
                fill={CLUSTER_FILL[note.cluster % CLUSTER_FILL.length]}
                stroke={active ? "#FFFFFF" : "#7A29A3"}
                strokeOpacity={active ? 0.9 : 0.55}
                strokeWidth={1.5}
                className="cursor-pointer transition-all"
                onMouseEnter={() => setHover(note.id)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect(note.id)}
              />
            </g>
          );
        })}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute z-10 w-[220px] -translate-x-1/2 rounded-lg border border-border bg-popover px-3 py-2 text-center text-xs text-foreground shadow-panel"
          style={{ left: hovered.x, top: hovered.y + 20 }}
        >
          {paperNotes.find((p) => p.id === hovered.id)?.title}
        </div>
      )}

      <div className="pointer-events-none absolute bottom-3 left-4 text-xs text-muted-foreground">
        {paperNotes.length} notes · {edges.length} links · hover a node for the title, click to open
      </div>
    </div>
  );
}
