import {useEffect, useState} from 'react';
import clsx from 'clsx';
import {type Decision, type DecisionValue, formatAmount} from './data';
import styles from './styles.module.css';

// The real path of a transaction, drawn as a transit map: the core calls
// the engine through the load balancer, the engine reads the cache and
// answers, and then publishes the decision to the SNS topic, which copies
// it to the three SQS queues and their consumers.

type NodeId =
  | 'core'
  | 'alb'
  | 'engine'
  | 'cache'
  | 'topic'
  | 'qCases'
  | 'qHistory'
  | 'qAnalytics'
  | 'cases'
  | 'history'
  | 'lake';

type Side = 'below' | 'above' | 'right' | 'left' | 'belowLeft' | 'aboveLeft' | 'aboveRight';

type Place = {x: number; y: number; side: Side; label: string};
type MapNode = {wide: Place; narrow: Place; big?: boolean};

// Two drawings of the same map: wide (left to right) and narrow (top to
// bottom, shorter labels so three columns fit a phone).
const NODES: Record<NodeId, MapNode> = {
  core: {
    wide: {x: 50, y: 120, side: 'below', label: 'Wallet core'},
    narrow: {x: 160, y: 30, side: 'right', label: 'Wallet core'},
  },
  alb: {
    wide: {x: 180, y: 120, side: 'below', label: 'Load balancer'},
    narrow: {x: 160, y: 110, side: 'right', label: 'Load balancer'},
  },
  engine: {
    wide: {x: 320, y: 120, side: 'below', label: 'Engine'},
    narrow: {x: 160, y: 200, side: 'right', label: 'Engine'},
    big: true,
  },
  cache: {
    wide: {x: 320, y: 40, side: 'above', label: 'Cache'},
    narrow: {x: 55, y: 200, side: 'above', label: 'Cache'},
  },
  topic: {
    wide: {x: 460, y: 120, side: 'belowLeft', label: 'Decisions topic'},
    narrow: {x: 160, y: 300, side: 'right', label: 'Decisions topic'},
  },
  qCases: {
    wide: {x: 590, y: 40, side: 'above', label: 'Cases queue'},
    narrow: {x: 55, y: 410, side: 'aboveLeft', label: 'Cases'},
  },
  qHistory: {
    wide: {x: 590, y: 120, side: 'below', label: 'History queue'},
    narrow: {x: 160, y: 410, side: 'aboveRight', label: 'History'},
  },
  qAnalytics: {
    wide: {x: 590, y: 200, side: 'below', label: 'Analytics queue'},
    narrow: {x: 255, y: 410, side: 'aboveRight', label: 'Analytics'},
  },
  cases: {
    wide: {x: 730, y: 40, side: 'above', label: 'Case opened'},
    narrow: {x: 55, y: 540, side: 'below', label: 'Case opened'},
  },
  history: {
    wide: {x: 730, y: 120, side: 'below', label: 'History DB'},
    narrow: {x: 160, y: 540, side: 'below', label: 'History DB'},
  },
  lake: {
    wide: {x: 730, y: 200, side: 'below', label: 'Data lake'},
    narrow: {x: 255, y: 540, side: 'below', label: 'Data lake'},
  },
};

const LINES: [NodeId, NodeId][] = [
  ['core', 'alb'],
  ['alb', 'engine'],
  ['engine', 'cache'],
  ['engine', 'topic'],
  ['topic', 'qCases'],
  ['topic', 'qHistory'],
  ['topic', 'qAnalytics'],
  ['qCases', 'cases'],
  ['qHistory', 'history'],
  ['qAnalytics', 'lake'],
];

const ROUTE_IN: NodeId[] = ['core', 'alb', 'engine'];
const ROUTE_CACHE: NodeId[] = ['engine', 'cache', 'engine'];
const ROUTE_BACK: NodeId[] = ['engine', 'alb', 'core'];
const ROUTES_OUT = {
  cases: ['engine', 'topic', 'qCases', 'cases'],
  history: ['engine', 'topic', 'qHistory', 'history'],
  analytics: ['engine', 'topic', 'qAnalytics', 'lake'],
} satisfies Record<string, NodeId[]>;

// After the decision: the answer goes back, and slightly later the
// published copies reach the queues.
const BACK_MS = 800;
const OUT_DELAY_MS = 300;
const OUT_MS = 1400;
const AFTER_MS = OUT_DELAY_MS + OUT_MS;

type Phase = 'enter' | 'cache' | 'rules' | 'after' | 'done';
type Point = {x: number; y: number};

type Props = {
  stage: number;
  finalStage: number;
  enterMs: number;
  cacheMs: number;
  decision: Decision;
  amount: string;
  currency: string;
  reduced: boolean;
};

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 600px)');
    setNarrow(query.matches);
    const onChange = () => setNarrow(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return narrow;
}

/** Milliseconds since `phase` began, refreshed every frame while moving. */
function usePhaseClock(phase: Phase): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (phase === 'rules' || phase === 'done') return undefined;
    const started = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      setElapsed(now - started);
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [phase]);
  return elapsed;
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const clamp = (t: number) => Math.max(0, Math.min(1, t));

/** The point at share `t` of the way along a route, by length. */
function along(route: NodeId[], t: number, pos: (id: NodeId) => Point): Point {
  const points = route.map(pos);
  const lengths = points.slice(1).map((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y));
  let left = ease(clamp(t)) * lengths.reduce((a, b) => a + b, 0);
  for (let i = 0; i < lengths.length; i++) {
    if (left <= lengths[i] || i === lengths.length - 1) {
      const share = lengths[i] === 0 ? 0 : Math.min(1, left / lengths[i]);
      return {
        x: points[i].x + (points[i + 1].x - points[i].x) * share,
        y: points[i].y + (points[i + 1].y - points[i].y) * share,
      };
    }
    left -= lengths[i];
  }
  return points[points.length - 1];
}

function labelPosition(node: Point, side: Side, big?: boolean) {
  const gap = big ? 26 : 20;
  switch (side) {
    case 'above':
      return {x: node.x, y: node.y - gap + 4, anchor: 'middle'};
    case 'below':
      return {x: node.x, y: node.y + gap + 8, anchor: 'middle'};
    case 'right':
      return {x: node.x + gap, y: node.y + 4, anchor: 'start'};
    case 'left':
      return {x: node.x - gap, y: node.y + 4, anchor: 'end'};
    case 'belowLeft':
      return {x: node.x - 6, y: node.y + gap + 8, anchor: 'end'};
    case 'aboveLeft':
      return {x: node.x - 12, y: node.y - 12, anchor: 'end'};
    case 'aboveRight':
      return {x: node.x + 12, y: node.y - 12, anchor: 'start'};
  }
}

function Token({at, text, tone}: {at: Point; text: string; tone?: DecisionValue}) {
  const width = text.length * 7.4 + 18;
  return (
    <g
      className={clsx(styles.mapToken, tone && styles[`tone${tone}`], tone && styles.mapTokenDecided)}
      transform={`translate(${at.x} ${at.y})`}>
      <rect x={-width / 2} y={-26} width={width} height={20} rx={10} />
      <text y={-12} textAnchor="middle">
        {text}
      </text>
      <circle r={5} />
    </g>
  );
}

export default function TransactionMap({
  stage,
  finalStage,
  enterMs,
  cacheMs,
  decision,
  amount,
  currency,
  reduced,
}: Props) {
  const narrow = useNarrow();
  const place = (id: NodeId): Place => (narrow ? NODES[id].narrow : NODES[id].wide);
  const pos = (id: NodeId): Point => place(id);

  const [settled, setSettled] = useState(false);
  const phase: Phase = reduced
    ? 'done'
    : stage >= finalStage
      ? settled
        ? 'done'
        : 'after'
      : stage <= 0
        ? 'enter'
        : stage === 1
          ? 'cache'
          : 'rules';
  const elapsed = usePhaseClock(phase);

  useEffect(() => {
    if (stage < finalStage) setSettled(false);
  }, [stage, finalStage]);
  useEffect(() => {
    if (phase !== 'after') return undefined;
    const timer = setTimeout(() => setSettled(true), AFTER_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  const decided = phase === 'after' || phase === 'done';
  const tone = decision.decision;
  const opensCase = decision.opens_case;
  const cacheMiss = decision.by_default;

  // The transaction itself.
  let txAt: Point;
  if (phase === 'enter') txAt = along(ROUTE_IN, elapsed / enterMs, pos);
  else if (phase === 'after') txAt = along(ROUTE_BACK, elapsed / BACK_MS, pos);
  else if (phase === 'done') txAt = pos('core');
  else txAt = pos('engine');

  // The engine asking the cache for the accounts, merchant and list.
  const probe = phase === 'cache' ? along(ROUTE_CACHE, elapsed / cacheMs, pos) : undefined;

  const outShare =phase === 'done' ? 1 : phase === 'after' ? (elapsed - OUT_DELAY_MS) / OUT_MS : -1;
  const outRoutes = Object.entries(ROUTES_OUT).map(([key, route]) => {
    // Without a case the cases consumer reads the event and stops at its queue.
    const stopsAtQueue = key === 'cases' && !opensCase;
    return {key, route: stopsAtQueue ? route.slice(0, 3) : route, share: outShare};
  });

  const lit = (a: NodeId, b: NodeId): boolean => {
    if (['core-alb', 'alb-engine'].includes(`${a}-${b}`)) return true;
    if (a === 'engine' && b === 'cache') return stage >= 1 || decided;
    if (!decided || outShare <= 0) return false;
    if (a === 'qCases' && b === 'cases') return opensCase && outShare >= 1;
    return true;
  };

  const STORES: NodeId[] = ['cases', 'history', 'lake'];
  const lastStore = (id: NodeId) =>
    STORES.includes(id) && decided && outShare >= 1 && (id !== 'cases' || opensCase);

  const width = narrow ? 320 : 800;
  const height = narrow ? 580 : 240;

  return (
    <figure
      className={clsx(styles.map, narrow && styles.mapNarrow)}
      aria-label={`The transaction travels from the wallet core to the engine, which answers ${tone}${opensCase ? ' and opens a case' : ''}, and then publishes the decision to the cases, history and analytics queues.`}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-hidden="true">
        {LINES.map(([a, b]) => {
          const p = pos(a);
          const q = pos(b);
          return (
            <line
              key={`${a}-${b}`}
              className={clsx(styles.mapLine, lit(a, b) && styles.mapLineLit)}
              x1={p.x}
              y1={p.y}
              x2={q.x}
              y2={q.y}
            />
          );
        })}

        {(Object.keys(NODES) as NodeId[]).map((id) => {
          const node = NODES[id];
          const p = place(id);
          const label = labelPosition(p, p.side, node.big);
          const missed = id === 'cache' && cacheMiss && (stage >= 2 || decided);
          return (
            <g
              key={id}
              className={clsx(
                styles.mapStation,
                id === 'engine' && phase === 'rules' && styles.mapStationBusy,
                missed && styles.mapStationMiss,
                lastStore(id) && styles.mapStationReached,
                id === 'cases' && !opensCase && styles.mapStationIdle,
              )}>
              <circle cx={p.x} cy={p.y} r={node.big ? 14 : 8} />
              <text x={label.x} y={label.y} textAnchor={label.anchor}>
                {id === 'cases' && !opensCase ? 'No case' : p.label}
              </text>
            </g>
          );
        })}

        {probe && <circle className={styles.mapProbe} r={5} cx={probe.x} cy={probe.y} />}

        {outRoutes.map(
          ({key, route, share}) =>
            share > 0 && (
              <circle
                key={key}
                className={clsx(styles.mapCopy, styles[`tone${tone}`])}
                r={5}
                cx={along(route as NodeId[], share, pos).x}
                cy={along(route as NodeId[], share, pos).y}
              />
            ),
        )}

        <Token
          at={txAt}
          text={decided ? tone : formatAmount(amount, currency)}
          tone={decided ? tone : undefined}
        />
      </svg>
    </figure>
  );
}
