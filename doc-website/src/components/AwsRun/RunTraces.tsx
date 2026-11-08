import clsx from 'clsx';
import Link from '@docusaurus/Link';
import DecisionBadge from '@site/src/components/Demo/DecisionBadge';
import {type Run, formatMs} from './data';
import styles from './styles.module.css';

type Props = {run: Run};

/** One row per story: what the engine decided against what the demo
 * expects, and what the system did with it, timed from the decision. */
export default function RunTraces({run}: Props) {
  const matching = run.scenarios.filter((s) => s.matches).length;
  return (
    <>
      <p className={styles.verdict}>
        {matching} of {run.scenarios.length} stories got the decision the demo shows.
      </p>
      <ol className={styles.traces}>
        {run.scenarios.map((s) => {
          const times = s.steps.map((step) => step.ms);
          return (
            <li key={s.id} className={clsx(styles.trace, !s.matches && styles.traceDiffers)}>
              <div className={styles.traceHead}>
                <Link to={`/demo?scenario=${s.id}`} className={styles.traceTitle}>
                  {s.title}
                </Link>
                <span className={styles.rn}>{s.rn}</span>
                <span className={styles.badges}>
                  <DecisionBadge decision={s.decision} size="small" />
                  {!s.matches && (
                    <span className={styles.expected}>
                      the demo expects <DecisionBadge decision={s.expected} size="small" />
                    </span>
                  )}
                </span>
              </div>
              <p className={styles.traceMeta}>
                {s.steps.length === 1
                  ? `1 request, ${formatMs(times[0])} at the client`
                  : `${s.steps.length} requests, ${formatMs(Math.min(...times))} to ${formatMs(
                      Math.max(...times),
                    )} at the client`}
                {s.rules_triggered.length > 0 && `; rules: ${s.rules_triggered.join(', ')}`}
                {s.risk_score > 0 && `; risk score ${s.risk_score}`}
              </p>
              <ol className={styles.timeline}>
                {s.trace.map((t) => (
                  <li key={t.label}>
                    <span className={styles.when}>
                      {t.at_ms === null ? '' : t.at_ms === 0 ? 'decided' : `+${formatMs(t.at_ms)}`}
                    </span>
                    <span>
                      <strong>{t.label}</strong>
                      {t.detail && <span className={styles.detail}> {t.detail}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            </li>
          );
        })}
      </ol>
      {run.skipped.length > 0 && (
        <p className={styles.small}>
          Not in this run:{' '}
          {run.skipped.map((s) => `${s.id.replace(/_/g, ' ')} (${s.reason})`).join('; ')}.
        </p>
      )}
    </>
  );
}
