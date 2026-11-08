import {useEffect, useState} from 'react';
import clsx from 'clsx';
import {type Decision, type DecisionValue, formatAmount} from './data';
import {
  EXTRA_LINES,
  LINES,
  type Place,
  ROUTE_BACK,
  ROUTE_CACHE,
  ROUTE_IN,
  ROUTES_OUT,
  STATIONS,
  STORES,
  type Side,
  type Station,
  type StationId,
} from './mapData';
import styles from './styles.module.css';

// The real path of a transaction, drawn as a transit map (stations in
// mapData.ts). The transaction moves with the decision flow's stages; any
// station can be selected to read what it does, and "the whole system"
// adds, dashed, the pieces that do not touch this transaction.

// After the decision: the answer goes back, and slightly later the
// published copies reach the queues and their consumers.
const BACK_MS = 800;
const OUT_DELAY_MS = 300;
const OUT_MS = 1600;
const AFTER_MS = OUT_DELAY_MS + OUT_MS;
const SYSTEM_SHIFT = 100; // room above the wide map for the extra stations

// Phones: short labels so three columns fit.
const NARROW_LABEL: Partial<Record<StationId, [string, string?]>> = {
  qCases: ['Cases'],
  qHistory: ['History'],
  qAnalytics: ['Analytics'],
  lCases: ['Lambda'],
  lHistory: ['Lambda'],
  lAnalytics: ['Lambda'],
};

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
function along(route: StationId[], t: number, pos: (id: StationId) => Point): Point {
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

/** Where a station's name and service go, by side. */
function labelAt(p: Point, side: Side, big?: boolean) {
  const gap = big ? 20 : 14;
  switch (side) {
    case 'above':
      return {x: p.x, y: p.y - gap - 12, sub: 14, anchor: 'middle'};
    case 'below':
      return {x: p.x, y: p.y + gap + 9, sub: 14, anchor: 'middle'};
    case 'right':
      return {x: p.x + gap + 4, y: p.y - 1, sub: 14, anchor: 'start'};
    case 'aboveLeft':
      return {x: p.x - 10, y: p.y - 26, sub: 14, anchor: 'end'};
    case 'aboveRight':
      return {x: p.x + 10, y: p.y - 26, sub: 14, anchor: 'start'};
  }
}

function Token({at, text, tone}: {at: Point; text: string; tone?: DecisionValue}) {
  const width = text.length * 7.4 + 18;
  return (
    <g
      className={clsx(styles.mapToken, tone && styles[`tone${tone}`], tone && styles.mapTokenDecided)}
      transform={`translate(${at.x} ${at.y})`}>
      <rect x={-width / 2} y={-28} width={width} height={20} rx={10} />
      <text y={-14} textAnchor="middle">
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
  const [system, setSystem] = useState(false);
  const [selected, setSelected] = useState<StationId | null>(null);
  const showExtras = system && !narrow;

  const place = (id: StationId): Place => {
    const s: Station = STATIONS[id];
    if (narrow && s.narrow) return s.narrow;
    return {...s.wide, y: s.wide.y + (showExtras ? SYSTEM_SHIFT : 0)};
  };
  const pos = (id: StationId): Point => place(id);

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

  let txAt: Point;
  if (phase === 'enter') txAt = along(ROUTE_IN, elapsed / enterMs, pos);
  else if (phase === 'after') txAt = along(ROUTE_BACK, elapsed / BACK_MS, pos);
  else if (phase === 'done') txAt = pos('core');
  else txAt = pos('engine');

  // The engine asking the cache for the accounts, merchant and list.
  const probe = phase === 'cache' ? along(ROUTE_CACHE, elapsed / cacheMs, pos) : undefined;

  const outShare = phase === 'done' ? 1 : phase === 'after' ? (elapsed - OUT_DELAY_MS) / OUT_MS : -1;
  // Without a case the cases consumer reads the decision and stops there.
  const outRoutes = ROUTES_OUT.map(({key, route}) => ({
    key,
    route: key === 'cases' && !opensCase ? route.slice(0, -1) : route,
  }));

  const lit = (a: StationId, b: StationId): boolean => {
    if (ROUTE_IN.includes(a) && ROUTE_IN.includes(b)) return true;
    if (b === 'cache') return stage >= 1 || decided;
    if (!decided || outShare <= 0) return false;
    if (b === 'cases') return opensCase && outShare >= 1;
    return true;
  };
  const reached = (id: StationId) =>
    STORES.includes(id) && decided && outShare >= 1 && (id !== 'cases' || opensCase);

  const ids = (Object.keys(STATIONS) as StationId[]).filter(
    (id) => showExtras || !(STATIONS[id] as Station).extra,
  );
  const width = narrow ? 320 : showExtras ? 900 : 800;
  const height = narrow ? 600 : showExtras ? 440 : 250;
  const info = selected ? (STATIONS[selected] as Station) : null;
  const extras = (Object.keys(STATIONS) as StationId[]).filter(
    (id) => (STATIONS[id] as Station).extra,
  );

  function line(a: StationId, b: StationId, extra: boolean, gap = 0) {
    const p = pos(a);
    const q = pos(b);
    const length = Math.hypot(q.x - p.x, q.y - p.y);
    const end = gap ? {x: q.x - ((q.x - p.x) * gap) / length, y: q.y - ((q.y - p.y) * gap) / length} : q;
    return (
      <line
        key={`${a}-${b}`}
        className={clsx(styles.mapLine, extra ? styles.mapLineExtra : lit(a, b) && styles.mapLineLit)}
        x1={p.x}
        y1={p.y}
        x2={end.x}
        y2={end.y}
      />
    );
  }

  return (
    <figure className={clsx(styles.map, narrow && styles.mapNarrow)}>
      <div className={styles.mapBar}>
        <button
          type="button"
          className={styles.replay}
          aria-pressed={system}
          onClick={() => setSystem((on) => !on)}>
          {system ? 'Show this transaction only' : 'Show the whole system'}
        </button>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`Map of the system. The transaction goes from the wallet core to the engine, which answers ${tone}${opensCase ? ' and opens a case' : ''}, and publishes the decision to the cases, history and analytics queues. Select a station to read what it does.`}>
        {showExtras && EXTRA_LINES.map(([a, b, gap]) => line(a, b, true, gap))}
        {LINES.map(([a, b]) => line(a, b, false))}

        {ids.map((id) => {
          const s = STATIONS[id] as Station;
          const p = place(id);
          const label = labelAt(p, p.side, s.big);
          const [name, service] =
            narrow && NARROW_LABEL[id]
              ? NARROW_LABEL[id]!
              : [id === 'cases' && !opensCase ? 'No case' : s.name, s.service];
          return (
            <g
              key={id}
              tabIndex={0}
              role="button"
              aria-label={`${s.name}, ${s.service}`}
              aria-pressed={selected === id}
              className={clsx(
                styles.mapStation,
                s.extra && styles.mapStationExtra,
                selected === id && styles.mapStationSelected,
                id === 'engine' && phase === 'rules' && styles.mapStationBusy,
                id === 'cache' && cacheMiss && (stage >= 2 || decided) && styles.mapStationMiss,
                reached(id) && styles.mapStationReached,
                id === 'cases' && !opensCase && styles.mapStationIdle,
              )}
              onClick={() => setSelected(id)}
              onFocus={() => setSelected(id)}
              onMouseEnter={() => setSelected(id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setSelected(id);
                }
              }}>
              <circle className={styles.mapHit} cx={p.x} cy={p.y} r={20} />
              <circle cx={p.x} cy={p.y} r={s.big ? 14 : 8} />
              <text x={label.x} y={label.y} textAnchor={label.anchor}>
                {name}
                {service && (
                  <tspan className={styles.mapService} x={label.x} dy={label.sub}>
                    {service}
                  </tspan>
                )}
              </text>
            </g>
          );
        })}

        {probe && <circle className={styles.mapProbe} r={5} cx={probe.x} cy={probe.y} />}

        {outShare > 0 &&
          outRoutes.map(({key, route}) => {
            const at = along(route, outShare, pos);
            return (
              <circle
                key={key}
                className={clsx(styles.mapCopy, styles[`tone${tone}`])}
                r={5}
                cx={at.x}
                cy={at.y}
              />
            );
          })}

        <Token
          at={txAt}
          text={decided ? tone : formatAmount(amount, currency)}
          tone={decided ? tone : undefined}
        />
      </svg>

      <figcaption className={styles.mapInfo} aria-live="polite">
        {info ? (
          <>
            <strong>{info.name}</strong> <span className={styles.mapInfoService}>{info.service}</span>
            <p>{info.about}</p>
          </>
        ) : (
          <p className={styles.mapHint}>Hover, tap or tab to a station to see what it does.</p>
        )}
      </figcaption>

      {system && narrow && (
        <ul className={styles.mapExtras} aria-label="The rest of the system">
          {extras.map((id) => {
            const s = STATIONS[id] as Station;
            return (
              <li key={id}>
                <strong>{s.name}</strong> <span className={styles.mapInfoService}>{s.service}</span>
                <p>{s.about}</p>
              </li>
            );
          })}
        </ul>
      )}
    </figure>
  );
}
