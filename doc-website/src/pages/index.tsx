import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HeroImage() {
  return (
    <div className={styles.visualWrap}>
      <div className={styles.visualGlow} aria-hidden="true" />
      <img
        className={styles.heroImage}
        src={useBaseUrl('/img/landing-shield.png')}
        alt="Shield over a transaction engine, with approved, held and rejected flows"
      />
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
          <HeroImage />
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
