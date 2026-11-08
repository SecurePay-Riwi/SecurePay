import {type Run, formatCount, formatMs, formatUtc} from './data';
import styles from './styles.module.css';

type Props = {run: Run};

/** CloudWatch during the run: the load balancer, the queues, the Lambdas. */
export default function RunMetrics({run}: Props) {
  const m = run.metrics;
  const lambdas = Object.entries(m.lambdas);
  return (
    <div className={styles.metrics}>
      <dl className={styles.facts}>
        <div>
          <dt>Engine latency in AWS</dt>
          <dd>
            p50 {formatMs(m.latency_ms.p50)}, p95 {formatMs(m.latency_ms.p95)}, p99{' '}
            {formatMs(m.latency_ms.p99)}
          </dd>
        </div>
        <div>
          <dt>Requests to the engine</dt>
          <dd>{formatCount(m.requests)}</dd>
        </div>
        <div>
          <dt>Default decisions</dt>
          <dd>{formatCount(m.fallback_decisions)}</dd>
        </div>
        <div>
          <dt>Messages read per queue</dt>
          <dd>
            {Object.entries(m.queues)
              .map(([q, n]) => `${q} ${formatCount(n)}`)
              .join(', ')}
          </dd>
        </div>
      </dl>
      {lambdas.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Lambda</th>
                <th>Invocations</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {lambdas.map(([name, v]) => (
                <tr key={name}>
                  <td>
                    <code>{name}</code>
                  </td>
                  <td>{formatCount(v.invocations)}</td>
                  <td className={v.errors > 0 ? styles.cellOver : undefined}>
                    {formatCount(v.errors)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className={styles.source}>
        CloudWatch, {formatUtc(run.window.from)} to {formatUtc(run.window.to)}, plus a minute on
        each side.
      </p>
    </div>
  );
}
