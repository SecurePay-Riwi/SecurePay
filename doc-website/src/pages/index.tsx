import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function DecisionFlow() {
  return (
    <div className={styles.visualWrap} aria-label="Illustration of SecurePay's transaction decision flow">
      <div className={styles.networkField} aria-hidden="true">
        <svg viewBox="0 0 560 500" fill="none" preserveAspectRatio="xMidYMid meet">
          <path className={styles.networkTrace} d="M18 122 108 170 166 92 250 142 330 62 410 112 520 54" />
          <path className={styles.networkTrace} d="M32 352 116 292 188 374 264 316 344 390 426 318 532 360" />
          <path className={styles.networkTrace} d="M108 170 116 292M166 92 188 374M250 142 264 316M330 62 344 390M410 112 426 318" />
          <path className={styles.networkTraceAccent} d="M18 122 108 170 250 142 330 62M188 374 264 316 426 318 532 360" />
          {[[18,122],[108,170],[166,92],[250,142],[330,62],[410,112],[520,54],[32,352],[116,292],[188,374],[264,316],[344,390],[426,318],[532,360]].map(([cx,cy], i) => (
            <circle key={i} className={i === 3 || i === 10 ? styles.networkNodeHot : styles.networkNode} cx={cx} cy={cy} r={i === 3 || i === 10 ? 4.5 : 3} />
          ))}
        </svg>
      </div>
      <div className={clsx(styles.signalTag, styles.signalTagTop)} aria-hidden="true">
        <span className={styles.signalTagDot} />
        <span><strong>DEVICE MATCH</strong><small>98.4% confidence</small></span>
      </div>
      <div className={clsx(styles.signalTag, styles.signalTagSide)} aria-hidden="true">
        <span className={styles.signalTagIcon}>↗</span>
        <span><strong>VELOCITY CHECK</strong><small>Pattern detected</small></span>
      </div>
      <div className={styles.visualGlow} aria-hidden="true" />
      <div className={styles.flowCard}>
        <div className={styles.windowBar}>
          <div className={styles.windowDots} aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <span className={styles.windowLabel}>SECUREPAY / DECISION FLOW</span>
          <span className={styles.windowBadge}>ILLUSTRATIVE</span>
        </div>

        <div className={styles.flowContent}>
          <div className={styles.flowIntro}>
            <span className={styles.flowIcon} aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <path d="M12 3 19 6v5c0 4.6-2.8 7.8-7 10-4.2-2.2-7-5.4-7-10V6l7-3Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                <path d="m9 12 2 2 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <div>
              <p className={styles.flowEyebrow}>REAL-TIME RISK EVALUATION</p>
              <p className={styles.flowTitle}>Every transaction tells a story.</p>
            </div>
          </div>

          <div className={styles.flowSteps}>
            <div className={styles.flowNode}>
              <span className={clsx(styles.nodeMarker, styles.markerViolet)}>01</span>
              <div>
                <strong>Transaction signal</strong>
                <span>Wallet activity enters</span>
              </div>
              <svg className={styles.nodeIcon} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M4 7h16M4 12h10M4 17h13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </div>
            <div className={styles.flowConnector}><span /></div>
            <div className={styles.flowNode}>
              <span className={clsx(styles.nodeMarker, styles.markerCyan)}>02</span>
              <div>
                <strong>Decision engine</strong>
                <span>Rules and risk signals evaluated</span>
              </div>
              <svg className={styles.nodeIcon} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
              </svg>
            </div>
          </div>

          <div className={styles.resultDivider}><span>DECISION</span></div>
          <div className={styles.decisionPills} aria-label="Possible decisions">
            <span className={styles.approve}><i /> APPROVE</span>
            <span className={styles.hold}><i /> HOLD</span>
            <span className={styles.reject}><i /> REJECT</span>
          </div>
          <p className={styles.flowFootnote}>One clear outcome. The right follow-up.</p>
        </div>
      </div>
      <div className={clsx(styles.orbit, styles.orbitOne)} aria-hidden="true" />
      <div className={clsx(styles.orbit, styles.orbitTwo)} aria-hidden="true" />
    </div>
  );
}

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();

  return (
    <header className={styles.hero}>
      <div className={styles.heroGridPattern} aria-hidden="true" />
      <div className={styles.heroAura} aria-hidden="true" />
      <div className="container">
        <div className={styles.heroLayout}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>
              <span className={styles.eyebrowPulse} />
              TRANSACTION SECURITY, WITH INTENT
            </p>
            <Heading as="h1" className={styles.heroTitle}>
              Trust the flow.
              <br />
              <span>Challenge the risk.</span>
            </Heading>
            <p className={styles.heroDescription}>
              {siteConfig.tagline}. SecurePay helps a digital wallet make clear,
              consistent decisions when a transaction needs a closer look.
            </p>
            <div className={styles.buttons}>
              <Link className={clsx('button button--primary button--lg', styles.primaryButton)} to="/docs/intro">
                Explore the docs <span aria-hidden="true">↗</span>
              </Link>
              <Link className={clsx('button button--secondary button--lg', styles.secondaryButton)} to="/docs/architecture/overview">
                <span className={styles.buttonPlay} aria-hidden="true">↗</span>
                Meet the architecture
              </Link>
            </div>
            <div className={styles.heroMeta}>
              <span className={styles.metaMark} aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 3 19 6v5c0 4.6-2.8 7.8-7 10-4.2-2.2-7-5.4-7-10V6l7-3Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                  <path d="m9 12 2 2 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <span>Built for the moments that matter.</span>
              <span className={styles.metaDot}>/</span>
              <span>Designed for clarity.</span>
            </div>
          </div>
          <DecisionFlow />
        </div>
      </div>
      <div className={styles.heroBottomLine} aria-hidden="true" />
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();

  return (
    <Layout title="Home" description={siteConfig.tagline}>
      <HomepageHeader />
      <main>
        <section className={styles.featuresIntro}>
          <div className="container">
            <div className={styles.sectionHeading}>
              <p className={styles.sectionEyebrow}>THE THINKING BEHIND THE FLOW</p>
              <Heading as="h2">Fast decisions. <span>Clear follow-through.</span></Heading>
              <p>Fraud prevention is more than a single verdict. It is a decision, the signal behind it, and what happens next.</p>
            </div>
            <HomepageFeatures />
            <div className={styles.bottomCta}>
              <div>
                <p className={styles.bottomCtaEyebrow}>READY TO GO DEEPER?</p>
                <Heading as="h3">Get to know the system.</Heading>
                <p>Start with the overview, then explore how the pieces work together.</p>
              </div>
              <Link className={clsx('button button--primary', styles.bottomCtaButton)} to="/docs/architecture/overview">
                Explore the architecture <span aria-hidden="true">→</span>
              </Link>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
