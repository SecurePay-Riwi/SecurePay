import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import LoadTestChart from '@site/src/components/AwsRun/LoadTestChart';
import RunMetrics from '@site/src/components/AwsRun/RunMetrics';
import RunTraces from '@site/src/components/AwsRun/RunTraces';
import {formatUtc, useAwsRun} from '@site/src/components/AwsRun/data';
import styles from './aws-run.module.css';

const COMMAND = `terraform -chdir=infra/terraform/envs/dev output -json > outputs.json
uv run python -m services.analytics.aws_run --outputs outputs.json \\
    --user <analyst e-mail> --password <password> --allow-self-signed`;

export default function AwsRun(): ReactNode {
  const {data, error} = useAwsRun();
  const run = data?.run;
  return (
    <Layout
      title="Recorded on AWS"
      description="The demo's stories and the load test, measured on the real deployment in AWS.">
      <main className={styles.page}>
        <header className={styles.hero}>
          <h1>Recorded on AWS</h1>
          <p>
            The <Link to="/demo">demo</Link> decides its stories with the engine's code in memory.
            This page shows the same stories sent to the real deployment: the engine on Fargate
            behind the load balancer, the queues, the Lambdas, the database and S3, plus the load
            test against the 200 ms limit.
          </p>
          {run && (
            <p className={styles.meta}>
              Run of {formatUtc(run.recorded_at)} in <code>{run.environment}</code> (
              {run.region}), {run.engine_tasks} engine tasks.
            </p>
          )}
        </header>

        {error && (
          <p className={styles.error} role="alert">
            The recorded data could not be loaded ({error}).
          </p>
        )}
        {!data && !error && <p>Loading…</p>}

        {data?.load_test && (
          <section className={styles.section} aria-labelledby="load-title">
            <h2 id="load-title">Load test: 50, 150 and 300 transactions per second</h2>
            <LoadTestChart load={data.load_test} />
          </section>
        )}

        {data && (
          <section className={styles.section} aria-labelledby="run-title">
            <h2 id="run-title">The demo's stories on AWS</h2>
            {run ? (
              <RunTraces run={run} />
            ) : (
              <div className={styles.empty}>
                <p>
                  No run recorded yet. With dev up, someone with access to AWS runs the recorder
                  once and commits <code>doc-website/static/aws-run/run.json</code>:
                </p>
                <pre>
                  <code>{COMMAND}</code>
                </pre>
                <p>
                  It sends every story with real seed accounts, waits for the Lambdas, follows each
                  decision to its case, history and evidence, and reads the run's metrics from
                  CloudWatch. <Link to="/docs/components/aws-run">How it works</Link>.
                </p>
              </div>
            )}
          </section>
        )}

        {run && (
          <section className={styles.section} aria-labelledby="metrics-title">
            <h2 id="metrics-title">What AWS measured during the run</h2>
            <RunMetrics run={run} />
          </section>
        )}

        <footer className={styles.note}>
          Every number on this page comes from AWS: CloudWatch, the cases API and S3, written to{' '}
          <code>static/aws-run/run.json</code> by <code>services/analytics/aws_run.py</code>. The
          infrastructure is destroyed after each session, so the page shows the last recording,
          not live data. See the <Link to="/docs/operations/runbook">runbook</Link>.
        </footer>
      </main>
    </Layout>
  );
}
