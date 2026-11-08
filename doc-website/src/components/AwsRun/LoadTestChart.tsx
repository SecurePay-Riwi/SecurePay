import clsx from 'clsx';
import {type LoadTest, formatCount} from './data';
import styles from './styles.module.css';

type Props = {load: LoadTest};

const W = 640;
const H = 300;
const PAD = {top: 24, right: 16, bottom: 44, left: 48};
const BARS = ['p50', 'p95', 'p99'] as const;

/** Latency of each step (p50, p95, p99 inside AWS) against the 200 ms
 * limit of RN-01. A p99 over the limit is drawn in the reject color. */
function StepChart({load}: Props) {
  const peak = Math.max(load.limit_ms, ...load.steps.map((s) => s.p99 ?? 0));
  const top = Math.ceil((peak * 1.15) / 50) * 50;
  const y = (ms: number) => PAD.top + (H - PAD.top - PAD.bottom) * (1 - ms / top);
  const band = (W - PAD.left - PAD.right) / load.steps.length;
  const bar = Math.min(34, (band - 24) / 3);
  const ticks = Array.from({length: top / 50 + 1}, (_, i) => i * 50);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={styles.chart}
      role="img"
      aria-label={`Latency per step: ${load.steps
        .map((s) => `${s.rate} tx/s p99 ${s.p99} ms`)
        .join(', ')}; the limit is ${load.limit_ms} ms.`}>
      {ticks.map((t) => (
        <g key={t}>
          <line className={styles.grid} x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
          <text className={styles.axis} x={PAD.left - 8} y={y(t) + 4} textAnchor="end">
            {t}
          </text>
        </g>
      ))}
      <text className={clsx(styles.axis, styles.unit)} x={PAD.left - 8} y={PAD.top - 10} textAnchor="end">
        ms
      </text>

      {load.steps.map((step, i) => {
        const x0 = PAD.left + band * i + (band - bar * 3 - 8) / 2;
        return (
          <g key={step.rate}>
            {BARS.map((key, j) => {
              const value = step[key];
              if (value === null) return null;
              const over = value > load.limit_ms;
              return (
                <g key={key}>
                  <rect
                    className={clsx(styles.bar, styles[`bar_${key}`], over && styles.barOver)}
                    x={x0 + j * (bar + 4)}
                    y={y(value)}
                    width={bar}
                    height={y(0) - y(value)}
                    rx={3}
                  />
                  <text
                    className={clsx(styles.value, over && styles.valueOver)}
                    x={x0 + j * (bar + 4) + bar / 2}
                    y={y(value) - 6}
                    textAnchor="middle">
                    {value}
                  </text>
                </g>
              );
            })}
            <text
              className={styles.step}
              x={PAD.left + band * i + band / 2}
              y={H - PAD.bottom + 20}
              textAnchor="middle">
              {step.rate} tx/s
            </text>
          </g>
        );
      })}

      <line
        className={styles.limit}
        x1={PAD.left}
        x2={W - PAD.right}
        y1={y(load.limit_ms)}
        y2={y(load.limit_ms)}
      />
      <text className={styles.limitText} x={PAD.left + 6} y={y(load.limit_ms) - 6}>
        {load.limit_ms} ms limit (RN-01)
      </text>
    </svg>
  );
}

/** p99 per minute over the whole test, when the run recorded it. */
function MinuteChart({load}: Props) {
  const points = load.series;
  if (points.length < 2) return null;
  const peak = Math.max(load.limit_ms, ...points.map((p) => p.p99));
  const top = Math.ceil((peak * 1.15) / 50) * 50;
  const h = 180;
  const x = (i: number) => PAD.left + ((W - PAD.left - PAD.right) * i) / (points.length - 1);
  const y = (ms: number) => 12 + (h - 12 - 28) * (1 - ms / top);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)} ${y(p.p99)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${h}`} className={styles.chart} role="img" aria-label="p99 per minute">
      <line className={styles.grid} x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} />
      <line
        className={styles.limit}
        x1={PAD.left}
        x2={W - PAD.right}
        y1={y(load.limit_ms)}
        y2={y(load.limit_ms)}
      />
      <path className={styles.line} d={path} />
      {points.map((p, i) => (
        <circle
          key={p.minute}
          className={clsx(styles.dot, p.p99 > load.limit_ms && styles.dotOver)}
          cx={x(i)}
          cy={y(p.p99)}
          r={3.5}
        />
      ))}
      <text className={styles.axis} x={PAD.left} y={h - 8}>
        {points[0].minute.slice(11, 16)} UTC
      </text>
      <text className={styles.axis} x={W - PAD.right} y={h - 8} textAnchor="end">
        {points[points.length - 1].minute.slice(11, 16)} UTC
      </text>
    </svg>
  );
}

export default function LoadTestChart({load}: Props) {
  const failing = load.steps.filter((s) => (s.p99 ?? 0) > load.limit_ms);
  return (
    <div className={styles.load}>
      <p className={styles.verdict}>
        {failing.length === 0
          ? `Every step kept its p99 under ${load.limit_ms} ms.`
          : `The p99 stayed under ${load.limit_ms} ms up to ${
              load.steps.filter((s) => (s.p99 ?? 0) <= load.limit_ms).at(-1)?.rate ?? 0
            } tx/s and went over it at ${failing.map((s) => `${s.rate} tx/s`).join(', ')}.`}
      </p>
      <div className={styles.legend} aria-hidden="true">
        <span className={styles.key_p50}>p50</span>
        <span className={styles.key_p95}>p95</span>
        <span className={styles.key_p99}>p99</span>
        <span className={styles.keyOver}>over the limit</span>
      </div>
      <StepChart load={load} />
      {load.series.length > 1 && (
        <>
          <h3 className={styles.subhead}>p99 per minute</h3>
          <MinuteChart load={load} />
        </>
      )}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Step</th>
              <th>Requests</th>
              <th>p50 / p95 / p99</th>
              <th>Default decisions</th>
              <th>5XX</th>
              <th>Engine CPU avg / max</th>
            </tr>
          </thead>
          <tbody>
            {load.steps.map((s) => (
              <tr key={s.rate}>
                <td>{s.rate} tx/s</td>
                <td>{formatCount(s.requests)}</td>
                <td className={clsx((s.p99 ?? 0) > load.limit_ms && styles.cellOver)}>
                  {s.p50} / {s.p95} / {s.p99} ms
                </td>
                <td>{s.default_pct === null ? '—' : `${s.default_pct} %`}</td>
                <td>{s.http_5xx}</td>
                <td>{s.cpu_avg === null ? '—' : `${s.cpu_avg} / ${s.cpu_max} %`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {load.client.requests !== undefined && (
        <p className={styles.small}>
          At the client (Locust): {formatCount(load.client.requests)} requests,{' '}
          {formatCount(load.client.failures)} failed, p50 {load.client.p50} ms, p99{' '}
          {load.client.p99} ms.
        </p>
      )}
      {load.notes && <p className={styles.small}>{load.notes}</p>}
      <p className={styles.source}>Source: {load.label}</p>
    </div>
  );
}
