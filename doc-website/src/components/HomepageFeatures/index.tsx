import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  eyebrow: string;
  to: string;
  description: ReactNode;
  icon: ReactNode;
  tone: 'violet' | 'cyan' | 'mint';
};

const FeatureList: FeatureItem[] = [
  {
    eyebrow: '01 / DECIDE',
    title: 'A decision in under 200 ms',
    to: '/docs/components/decision-engine',
    tone: 'violet',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M13 2 4.5 13h6L10 22l9.5-12h-6L13 2Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    ),
    description: (
      <>
        The wallet core sends each transaction to the decision engine and gets
        back <code>APPROVE</code>, <code>HOLD</code> or <code>REJECT</code>.
        Idempotency and time windows live in Valkey.
      </>
    ),
  },
  {
    eyebrow: '02 / RESPOND',
    title: 'Keep the flow moving',
    to: '/docs/components/messaging',
    tone: 'cyan',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M4 5.5h16v10H9l-5 4v-14Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M8 9h8M8 12h5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
    description: (
      <>
        Each decision is published to SNS and fanned out to SQS queues for
        cases, history and analytics. Follow-up work stays outside the
        transaction request path.
      </>
    ),
  },
  {
    eyebrow: '03 / UNDERSTAND',
    title: 'Test with reproducible data',
    to: '/docs/components/generator',
    tone: 'mint',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <ellipse cx="12" cy="5" rx="7.5" ry="2.5" stroke="currentColor" strokeWidth="1.6" />
        <path d="M4.5 5v7c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5V5M4.5 12v7c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-7" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
    description: (
      <>
        Seeded data and a configurable generator simulate wallet activity,
        fraud patterns and data defects across Windows and Linux environments.
      </>
    ),
  },
];

function Feature({eyebrow, title, to, description, icon, tone}: FeatureItem) {
  return (
    <div className={clsx('col col--4', styles.featureColumn)}>
      <article className={clsx(styles.featureCard, styles[tone])}>
        <div className={styles.cardTop}>
          <span className={styles.featureIcon}>{icon}</span>
          <span className={styles.featureEyebrow}>{eyebrow}</span>
        </div>
        <Heading as="h3" className={styles.featureTitle}>
          <Link to={to}>{title}</Link>
        </Heading>
        <p className={styles.featureDescription}>{description}</p>
        <Link className={styles.featureLink} to={to}>
          Explore component <span aria-hidden="true">↗</span>
        </Link>
      </article>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <div className={styles.features}>
      <div className="row">
        {FeatureList.map((feature) => (
          <Feature key={feature.eyebrow} {...feature} />
        ))}
      </div>
    </div>
  );
}
