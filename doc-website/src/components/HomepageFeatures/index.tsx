import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  to: string;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'A decision in under 200 ms',
    to: '/docs/components/decision-engine',
    description: (
      <>
        The wallet core sends every transaction to the decision engine and gets
        back APPROVE, HOLD or REJECT. Idempotency and time windows live in
        Valkey, so nothing slow sits in the request path.
      </>
    ),
  },
  {
    title: 'Everything else happens later',
    to: '/docs/components/messaging',
    description: (
      <>
        Each decision is published to SNS and fanned out to three SQS queues
        (cases, history, analytics). If a consumer falls behind or SNS is down,
        the engine keeps answering.
      </>
    ),
  },
  {
    title: 'Reproducible data',
    to: '/docs/components/generator',
    description: (
      <>
        A seed loads users, accounts, devices, merchants and restricted lists.
        A generator plays the wallet core and injects labeled fraud patterns
        and data defects, the same on Windows and Linux.
      </>
    ),
  },
];

function Feature({title, to, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="padding-horiz--md padding-vert--md">
        <Heading as="h3">
          <Link to={to}>{title}</Link>
        </Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
