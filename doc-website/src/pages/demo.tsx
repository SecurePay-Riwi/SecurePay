import {type ReactNode, useEffect, useState} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import DecisionFlow from '@site/src/components/Demo/DecisionFlow';
import ScenarioPicker from '@site/src/components/Demo/ScenarioPicker';
import StoryTimeline from '@site/src/components/Demo/StoryTimeline';
import {useDemoData} from '@site/src/components/Demo/data';
import styles from './demo.module.css';

const PARAM = 'scenario';

/** The scenario in the URL (?scenario=mule), so a link opens it. */
function useSelectedScenario(ids: string[]): [string, (id: string) => void] {
  const [selected, setSelected] = useState('');
  useEffect(() => {
    if (ids.length === 0) return;
    const fromUrl = new URLSearchParams(window.location.search).get(PARAM);
    setSelected(fromUrl && ids.includes(fromUrl) ? fromUrl : ids[0]);
  }, [ids.join(',')]);

  function select(id: string) {
    setSelected(id);
    const url = new URL(window.location.href);
    url.searchParams.set(PARAM, id);
    window.history.replaceState(null, '', url);
  }
  return [selected, select];
}

export default function Demo(): ReactNode {
  const {data, error} = useDemoData();
  const ids = data?.scenarios.map((s) => s.id) ?? [];
  const [selected, select] = useSelectedScenario(ids);
  const scenario = data?.scenarios.find((s) => s.id === selected);

  return (
    <Layout
      title="Demo"
      description="Pick a story and watch the antifraud engine decide it, rule by rule.">
      <main className={styles.page}>
        <header className={styles.hero}>
          <p className={styles.eyebrow}>Interactive demo</p>
          <h1>How the engine decides a transaction</h1>
          <p>
            Every transaction gets APPROVE, HOLD or REJECT in under 200 ms. The
            engine checks it against a versioned catalog of rules and the
            account's recent history. Pick a story to see it decided.
          </p>
        </header>

        {error && (
          <p className={styles.error} role="alert">
            The scenarios could not be loaded ({error}).
          </p>
        )}
        {!data && !error && <p className={styles.loading}>Loading the scenarios…</p>}

        {data && scenario && (
          <>
            <ScenarioPicker scenarios={data.scenarios} selected={selected} onSelect={select} />
            <section className={styles.storyBox} aria-labelledby="story-title">
              <h2 id="story-title">
                {scenario.title} <span className={styles.rn}>{scenario.rn}</span>
              </h2>
              <p>{scenario.story}</p>
              <StoryTimeline scenario={scenario} />
            </section>
            <DecisionFlow key={scenario.id} data={data} scenario={scenario} />
          </>
        )}

        <footer className={styles.note}>
          These decisions were not made live: the engine's own code computed them
          ({data?.generated_from ?? 'services/analytics/demo.py'}) with the code
          default catalog and the fixed 2026-10-01 exchange rates, and a test keeps
          them in step with the engine. See the{' '}
          <Link to="/docs/architecture/overview">architecture</Link> and{' '}
          <Link to="/docs/components/demo">how the demo is built</Link>.
        </footer>
      </main>
    </Layout>
  );
}
