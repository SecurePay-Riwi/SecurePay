import {type ReactNode, useEffect, useState} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import {type Scenario, protagonist, usePrefersReducedMotion} from './data';
import styles from './styles.module.css';

// The 4-hour case clock (RN-09) runs in about 3 seconds here.
const CLOCK_MS = 3000;
const CLOCK_TICK_MS = 50;

type Props = {scenario: Scenario};

type Item = {key: string; title: string; rn?: string; body: ReactNode; doc: string};

function useCaseClock(limit: number, reduced: boolean, run: number): number {
  const [minutes, setMinutes] = useState(reduced ? limit : 0);
  useEffect(() => {
    if (reduced || limit === 0) {
      setMinutes(limit);
      return undefined;
    }
    setMinutes(0);
    const started = Date.now();
    const timer = setInterval(() => {
      const share = Math.min(1, (Date.now() - started) / CLOCK_MS);
      setMinutes(Math.round(share * limit));
      if (share === 1) clearInterval(timer);
    }, CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, [limit, reduced, run]);
  return minutes;
}

function clock(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}:${String(m).padStart(2, '0')}`;
}

export default function AfterTimeline({scenario}: Props) {
  const {after} = scenario;
  const decision = protagonist(scenario).decision;
  const reduced = usePrefersReducedMotion();
  const [run, setRun] = useState(0);
  const limit = after.case_due_minutes ?? 0;
  const minutes = useCaseClock(limit, reduced, run);
  const escalated = after.opens_case && minutes >= limit;

  const items: Item[] = [
    {
      key: 'publish',
      title: 'Published, without waiting',
      body: (
        <>
          The answer goes back to the core first. Then the decision is published
          to the <code>decisions</code> SNS topic, which copies it to the queues{' '}
          {after.queues.map((q, i) => (
            <span key={q}>
              {i > 0 && (i === after.queues.length - 1 ? ' and ' : ', ')}
              <code>{q}</code>
            </span>
          ))}
          .
        </>
      ),
      doc: '/docs/components/messaging',
    },
    {
      key: 'history',
      title: '30-day account history',
      body: 'The history consumer stores the transaction for each account involved, whatever the decision. Analysts read it with the case.',
      doc: '/docs/components/consumers',
    },
  ];

  if (after.compliance_report) {
    items.push({
      key: 'compliance',
      title: 'Report to compliance',
      rn: 'RN-06',
      body: 'One report per listed owner, sent to the compliance officer in the next alerts run.',
      doc: '/docs/components/cases',
    });
  }

  if (after.opens_case) {
    items.push(
      {
        key: 'case',
        title: escalated ? 'Case escalated to the supervisor' : 'Case opened for an analyst',
        rn: 'RN-09',
        body: (
          <div className={styles.caseClock}>
            <div className={styles.clockBar} aria-hidden="true">
              <span style={{width: `${(minutes / limit) * 100}%`}} />
            </div>
            <span className={styles.clockText}>
              {escalated
                ? `Not resolved in ${clock(limit)} h: ESCALATED`
                : `Open for ${clock(minutes)} h of ${clock(limit)} h`}
            </span>
            <button
              type="button"
              className={styles.replay}
              onClick={() => setRun((n) => n + 1)}>
              ↻ Clock
            </button>
          </div>
        ),
        doc: '/docs/components/cases',
      },
      {
        key: 'resolve',
        title: 'The analyst resolves it',
        body: 'FRAUD makes the final decision REJECT; LEGITIMATE makes it APPROVE. Resolved is final.',
        doc: '/docs/components/cases',
      },
      {
        key: 'evidence',
        title: 'Evidence kept, unchangeable',
        rn: 'RN-12',
        body: (
          <>
            The case, its transactions, the decision and the analyst go to{' '}
            <code>{after.evidence}</code>.
          </>
        ),
        doc: '/docs/components/cases',
      },
    );
  } else {
    items.push({
      key: 'no-case',
      title: 'No case',
      body: 'No rule that opens a case fired, so no analyst needs to look at it.',
      doc: '/docs/components/cases',
    });
  }

  if (decision.decision === 'APPROVE') {
    items.push({
      key: 'reconciliation',
      title: 'Reconciled the next night',
      rn: 'RN-10',
      body: "Approved transactions are matched with the payment partner's statement by reference, amount (±0.01) and date (±1 day).",
      doc: '/docs/components/reconciliation',
    });
  }

  items.push({
    key: 'analytics',
    title: 'Analytics and Power BI',
    body: 'The analytics consumer writes it to the data lake; the nightly ETL builds the dimensional model the dashboard reads.',
    doc: '/docs/components/analytics',
  });

  return (
    <section className={styles.after} aria-labelledby="after-title">
      <h2 id="after-title">What happens next</h2>
      <ol className={styles.afterList}>
        {items.map((item) => (
          <li
            key={item.key}
            className={clsx(styles.afterItem, item.key === 'case' && escalated && styles.afterAlert)}>
            <div className={styles.afterHead}>
              <strong>{item.title}</strong>
              {item.rn && <span className={styles.ruleRn}>{item.rn}</span>}
              <Link className={styles.afterDoc} to={item.doc}>
                Docs
              </Link>
            </div>
            <div className={styles.afterBody}>{item.body}</div>
          </li>
        ))}
      </ol>
    </section>
  );
}
