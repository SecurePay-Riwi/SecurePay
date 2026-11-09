import {type ReactNode, useEffect, useMemo, useState} from 'react';
import Layout from '@theme/Layout';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './live-demo.module.css';

type Currency = 'USD' | 'COP' | 'EUR' | 'JPY';
type TransactionType = 'P2P' | 'QR' | 'RECARGA' | 'RETIRO';
type TransactionRequest = {
  id: string;
  type: TransactionType;
  channel: string;
  amount: string;
  currency: Currency;
  transaction_date: string;
  device_id: string;
  source_account_id?: string;
  source_balance_before?: string;
  source_balance_after?: string;
  destination_account_id?: string;
  destination_balance_before?: string;
  destination_balance_after?: string;
  merchant_id?: string;
};
type SecurityEventRequest = {
  id: string;
  type: 'DEVICE_CHANGE' | 'PASSWORD_CHANGE';
  user_id: string;
  account_id: string;
  device_id: string;
  event_date: string;
};
type RequestBody = TransactionRequest | SecurityEventRequest;
type LiveStep = {
  kind: 'transaction' | 'security_event';
  label: string;
  path: '/transactions' | '/security-events';
  body: RequestBody;
};
type Scenario = {
  id: string;
  title: string;
  rule: string;
  description: string;
  steps: LiveStep[];
};
type AccountData = {
  format_version: number;
  accounts: Record<Currency, string[]>;
  merchants: string[];
  restricted_account_id: string;
};
type Execution = {
  ok: boolean;
  status: number | null;
  elapsedMs: number | null;
  body: unknown;
  error?: string;
};
type RunState = Record<string, Execution[]>;

const ACCOUNT_DATA_URL = '/live-demo/accounts.json';
const TIMEOUT_MS = 20_000;

function uuid(): string {
  return globalThis.crypto.randomUUID();
}

function shuffled<T>(values: T[]): T[] {
  const result = [...values];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const randomValue = globalThis.crypto.getRandomValues(new Uint32Array(1))[0];
    const j = randomValue % (i + 1);
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

function selectAccounts(values: string[], count: number): string[] {
  if (values.length < count) {
    throw new Error(`Not enough seed accounts: need ${count}, found ${values.length}.`);
  }
  return shuffled(values).slice(0, count);
}

function tx(
  type: TransactionType,
  when: Date,
  amount: string,
  currency: Currency,
  options: {
    source?: string;
    destination?: string;
    merchant?: string;
    channel?: string;
    device: string;
    balance?: string;
  },
): TransactionRequest {
  const amountValue = Number(amount);
  const balance = options.balance ?? '5000.00';
  const body: TransactionRequest = {
    id: uuid(),
    type,
    channel: options.channel ?? 'APP',
    amount,
    currency,
    device_id: options.device,
    transaction_date: when.toISOString(),
  };
  if (options.source) {
    body.source_account_id = options.source;
    body.source_balance_before = balance;
    body.source_balance_after = (Number(balance) - amountValue).toFixed(2);
  }
  if (options.destination) {
    body.destination_account_id = options.destination;
    body.destination_balance_before = balance;
    body.destination_balance_after = (Number(balance) + amountValue).toFixed(2);
  }
  if (options.merchant) body.merchant_id = options.merchant;
  return body;
}

function buildScenarios(accounts: AccountData, now: Date): Scenario[] {
  const usd = selectAccounts(accounts.accounts.USD, 17);
  const cop = selectAccounts(accounts.accounts.COP, 2);
  const ago = (minutes: number) => new Date(now.getTime() - minutes * 60_000);
  const device = () => uuid();
  const step = (
    label: string,
    body: RequestBody,
    kind: LiveStep['kind'] = 'transaction',
  ): LiveStep => ({
    kind,
    label,
    path: kind === 'transaction' ? '/transactions' : '/security-events',
    body,
  });

  const velocityDevice = device();
  const mule = usd[6];
  const sharedDevice = device();
  const sharedMerchant = accounts.merchants[
    globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % accounts.merchants.length
  ];
  const takeoverDevice = device();

  return [
    {
      id: 'normal',
      title: 'Everyday transfer',
      rule: 'RN-01',
      description: 'A regular P2P transfer between two active, unlisted seed accounts.',
      steps: [
        step(
          'P2P transfer of USD 28',
          tx('P2P', ago(1), '28.00', 'USD', {
            source: usd[0],
            destination: usd[1],
            device: device(),
          }),
        ),
      ],
    },
    {
      id: 'over_limit',
      title: 'Default decision',
      rule: 'RN-01',
      description: 'The sender is not in the engine cache; the configured fallback decides.',
      steps: [
        step(
          'P2P of USD 75 from an account not in the cache',
          tx('P2P', ago(1), '75.00', 'USD', {
            source: uuid(),
            destination: usd[2],
            device: device(),
          }),
        ),
      ],
    },
    {
      id: 'restricted_list',
      title: 'Restricted list',
      rule: 'RN-06',
      description: 'The destination account belongs to an owner in the seeded restricted list.',
      steps: [
        step(
          'P2P transfer of USD 120 to a listed owner',
          tx('P2P', ago(1), '120.00', 'USD', {
            source: usd[3],
            destination: accounts.restricted_account_id,
            device: device(),
          }),
        ),
      ],
    },
    {
      id: 'velocity',
      title: 'Velocity',
      rule: 'RN-02',
      description: 'Six P2P transfers from one account arrive within ten minutes.',
      steps: [0, 1, 3, 4, 6, 8].map((minutes, index) =>
        step(
          `Transfer ${index + 1} of 6, USD 15`,
          tx('P2P', ago(9 - minutes), '15.00', 'USD', {
            source: usd[4],
            destination: usd[5],
            device: velocityDevice,
          }),
        ),
      ),
    },
    {
      id: 'mule',
      title: 'Mule account',
      rule: 'RN-03',
      description: 'Three senders transfer USD 300 each, then the recipient withdraws 85% of the total.',
      steps: [
        ...[7, 8, 9].map((sender, index) =>
          step(
            `Sender ${index + 1} transfers USD 300`,
            tx('P2P', ago(29 - 4 * index), '300.00', 'USD', {
              source: usd[sender],
              destination: mule,
              device: device(),
            }),
          ),
        ),
        step(
          'Withdraws USD 765 of USD 900',
          tx('RETIRO', ago(1), '765.00', 'USD', {
            source: mule,
            channel: 'CAJERO',
            device: device(),
            balance: '900.00',
          }),
        ),
      ],
    },
    {
      id: 'shared_device',
      title: 'Shared device',
      rule: 'RN-04',
      description: 'Four different active accounts pay the same merchant from one device.',
      steps: usd.slice(10, 14).map((account, index) =>
        step(
          `Account ${index + 1} pays USD 12 from the same device`,
          tx('QR', ago(8 - 2 * index), '12.00', 'USD', {
            source: account,
            merchant: sharedMerchant,
            device: sharedDevice,
          }),
        ),
      ),
    },
    {
      id: 'splitting',
      title: 'Splitting',
      rule: 'RN-05',
      description: 'Three withdrawals below the individual limit exceed the daily total.',
      steps: [360, 180, 1].map((minutes, index) =>
        step(
          `Withdrawal ${index + 1} of 3, USD 4,000`,
          tx('RETIRO', ago(minutes), '4000.00', 'USD', {
            source: usd[14],
            channel: 'CAJERO',
            device: device(),
            balance: '15000.00',
          }),
        ),
      ),
    },
    {
      id: 'account_takeover',
      title: 'Account takeover',
      rule: 'RN-07',
      description: 'Device and password changes precede a USD 350 transfer from the new device.',
      steps: [
        ...[
          {type: 'DEVICE_CHANGE' as const, label: 'Device changed', minutes: 20},
          {type: 'PASSWORD_CHANGE' as const, label: 'Password changed', minutes: 15},
        ].map(({type, label, minutes}) =>
          step(
            label,
            {
              id: uuid(),
              type,
              user_id: uuid(),
              account_id: usd[15],
              device_id: takeoverDevice,
              event_date: ago(minutes).toISOString(),
            },
            'security_event',
          ),
        ),
        step(
          'P2P transfer of USD 350 from the new device',
          tx('P2P', ago(1), '350.00', 'USD', {
            source: usd[15],
            destination: usd[16],
            device: takeoverDevice,
          }),
        ),
      ],
    },
    {
      id: 'currency',
      title: 'Other currency',
      rule: 'RN-11',
      description: 'A COP transaction is evaluated and reported using the engine exchange rate.',
      steps: [
        step(
          'P2P transfer of COP 95,000',
          tx('P2P', ago(1), '95000.00', 'COP', {
            source: cop[0],
            destination: cop[1],
            device: device(),
            balance: '20000000.00',
          }),
        ),
      ],
    },
  ];
}

function displayDecision(
  scenario: Scenario | undefined,
  executions: Execution[] | undefined,
): string | null {
  if (
    !scenario ||
    !executions ||
    executions.length !== scenario.steps.length ||
    executions.some((execution) => !execution.ok)
  ) {
    return null;
  }
  for (let index = executions.length - 1; index >= 0; index -= 1) {
    if (scenario.steps[index].kind !== 'transaction') continue;
    const body = executions[index].body;
    if (typeof body === 'object' && body !== null && 'decision' in body) {
      return String(body.decision);
    }
  }
  return null;
}

function formatBody(value: unknown): string {
  if (typeof value === 'string') return value || '(empty response)';
  return JSON.stringify(value, null, 2) ?? '(empty response)';
}

function normalizeApiBase(value: string): string {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error('Enter a complete URL, for example https://api.example.com.');
  }
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol !== 'https:' && !(local && url.protocol === 'http:')) {
    throw new Error('Use HTTPS; HTTP is allowed only for localhost development.');
  }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('Enter only the API base URL: no path, credentials, query, or fragment.');
  }
  return url.origin;
}

async function executeScenario(
  scenario: Scenario,
  baseUrl: string,
  onResult: (result: Execution) => void,
): Promise<void> {
  for (const step of scenario.steps) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    const started = performance.now();
    try {
      const response = await fetch(`${baseUrl}${step.path}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(step.body),
        signal: controller.signal,
      });
      const text = await response.text();
      let body: unknown = text;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      const result: Execution = {
        ok: response.ok,
        status: response.status,
        elapsedMs: Math.round(performance.now() - started),
        body,
      };
      onResult(result);
      if (!response.ok) return;
    } catch (error) {
      const message =
        controller.signal.aborted
          ? `Request timed out after ${TIMEOUT_MS / 1000} seconds.`
          : error instanceof Error
            ? error.message
            : String(error);
      onResult({
        ok: false,
        status: null,
        elapsedMs: Math.round(performance.now() - started),
        body: null,
        error: message,
      });
      return;
    } finally {
      window.clearTimeout(timeout);
    }
  }
}

export default function LiveDemo(): ReactNode {
  const accountsUrl = useBaseUrl(ACCOUNT_DATA_URL);
  const [accounts, setAccounts] = useState<AccountData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [apiUrl, setApiUrl] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [runs, setRuns] = useState<RunState>({});
  const [runningId, setRunningId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(accountsUrl, {signal: controller.signal})
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<AccountData>;
      })
      .then((data) => {
        if (data.format_version !== 1) {
          throw new Error(`Unsupported account data format ${data.format_version}.`);
        }
        setAccounts(data);
        const prepared = buildScenarios(data, new Date());
        setScenarios(prepared);
        setSelectedId(prepared[0].id);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => controller.abort();
  }, [accountsUrl]);

  const selected = useMemo(
    () => scenarios.find((scenario) => scenario.id === selectedId),
    [scenarios, selectedId],
  );
  const executions = selected ? runs[selected.id] : undefined;
  const failedIndex = executions?.findIndex((execution) => !execution.ok) ?? -1;
  const finalDecision = displayDecision(selected, executions);
  const decisionLabel =
    finalDecision === 'APPROVE'
      ? 'Approved'
      : finalDecision === 'REJECT'
        ? 'REJECTED'
        : finalDecision;

  function prepareNewRun() {
    if (!accounts || runningId) return;
    try {
      const prepared = buildScenarios(accounts, new Date());
      setScenarios(prepared);
      setSelectedId(prepared[0].id);
      setRuns({});
      setInputError(null);
    } catch (error) {
      setInputError(error instanceof Error ? error.message : String(error));
    }
  }

  async function runSelected() {
    if (!selected || runningId) return;
    let baseUrl: string;
    try {
      baseUrl = normalizeApiBase(apiUrl);
    } catch (error) {
      setInputError(error instanceof Error ? error.message : String(error));
      return;
    }

    setInputError(null);
    setRuns((current) => ({...current, [selected.id]: []}));
    setRunningId(selected.id);
    try {
      await executeScenario(selected, baseUrl, (result) => {
        setRuns((current) => ({
          ...current,
          [selected.id]: [...(current[selected.id] ?? []), result],
        }));
      });
    } finally {
      setRunningId(null);
    }
  }

  return (
    <Layout
      title="Live AWS demo"
      description="Send real transaction scenarios from the browser to the deployed SecurePay engine.">
      <main className={styles.page}>
        <header className={styles.hero}>
          <p className={styles.eyebrow}>Live demo</p>
          <h1>Send scenarios to the real engine</h1>
          <p>
            Choose a rule, inspect the exact requests, and explicitly send the complete
            sequence to the deployed API. Decisions and reasons below come from the
            response received from that API.
          </p>
        </header>

        <section className={styles.connection} aria-labelledby="connection-title">
          <h2 id="connection-title">Connect to the engine</h2>
          <label htmlFor="api-url">Engine base URL</label>
          <div className={styles.connectionRow}>
            <input
              id="api-url"
              type="url"
              autoComplete="url"
              placeholder="https://your-engine.example.com"
              value={apiUrl}
              onChange={(event) => setApiUrl(event.target.value)}
            />
            <button type="button" onClick={runSelected} disabled={!selected || runningId !== null}>
              {runningId === selected?.id ? 'Sending sequence…' : 'Send this scenario'}
            </button>
          </div>
          <p className={styles.help}>
            The base URL has no path. To find the current AWS host, run{' '}
            <code>terraform -chdir=infra/terraform/envs/dev output -raw alb_dns_name</code>{' '}
            and prefix it with <code>https://</code>.
          </p>
          {inputError && <p className={styles.error} role="alert">{inputError}</p>}
          {loadError && (
            <p className={styles.error} role="alert">
              Could not load the active seed accounts ({loadError}).
            </p>
          )}
          <p className={styles.warning}>
            The deployed engine must include this CORS configuration. AWS dev currently
            uses a self-signed certificate unless a domain with a trusted certificate
            is configured; browsers will block that TLS connection. This demo sends
            synthetic requests without authentication.
          </p>
        </section>

        {scenarios.length > 0 && (
          <>
            <div className={styles.scenarioHeading}>
              <h2>Scenarios</h2>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={prepareNewRun}
                disabled={runningId !== null}>
                Prepare fresh requests
              </button>
            </div>
            <div className={styles.tabs} aria-label="Transaction scenarios">
              {scenarios.map((scenario) => (
                <button
                  type="button"
                  aria-pressed={selectedId === scenario.id}
                  className={selectedId === scenario.id ? styles.activeTab : undefined}
                  key={scenario.id}
                  onClick={() => setSelectedId(scenario.id)}>
                  {scenario.title}
                </button>
              ))}
            </div>
            {selected && (
              <section className={styles.scenario}>
                <header className={styles.scenarioTitle}>
                  <div>
                    <p className={styles.eyebrow}>{selected.rule}</p>
                    <h2>{selected.title}</h2>
                  </div>
                  {decisionLabel && (
                    <span
                      className={`${styles.decision} ${
                        finalDecision === 'APPROVE'
                          ? styles.approved
                          : finalDecision === 'REJECT'
                            ? styles.rejected
                            : styles.held
                      }`}>
                      {decisionLabel}
                    </span>
                  )}
                </header>
                <p>{selected.description}</p>
                <p className={styles.sequenceNote}>
                  This scenario contains {selected.steps.length} ordered request
                  {selected.steps.length === 1 ? '' : 's'}. Send the whole sequence;
                  later steps depend on the earlier history.
                </p>
                <div className={styles.steps}>
                  {selected.steps.map((step, index) => {
                    const result = executions?.[index];
                    const skipped = failedIndex >= 0 && index > failedIndex;
                    return (
                      <details key={`${selected.id}-${step.body.id}`} open={index === 0}>
                        <summary>
                          <span>
                            {index + 1}. {step.label}
                          </span>
                          <span className={styles.stepMeta}>
                            POST {step.path}
                            {result &&
                              ` · ${
                                result.ok
                                  ? `HTTP ${result.status}`
                                  : `Failed (${result.status ?? 'network error'})`
                              } · ${result.elapsedMs} ms`}
                          </span>
                        </summary>
                        <div className={styles.payloads}>
                          <div>
                            <h3>Request JSON</h3>
                            <pre>{JSON.stringify(step.body, null, 2)}</pre>
                          </div>
                          {result && (
                            <div>
                              <h3>
                                Actual response
                                {result.status !== null ? ` · HTTP ${result.status}` : ''}
                              </h3>
                              {result.error && <p className={styles.error}>{result.error}</p>}
                              <pre>{formatBody(result.body)}</pre>
                              {typeof result.body === 'object' &&
                                result.body !== null &&
                                'decision_reason' in result.body && (
                                  <p className={styles.reason}>
                                    Reason: {String(result.body.decision_reason)}
                                  </p>
                                )}
                            </div>
                          )}
                          {skipped && (
                            <p className={styles.error}>
                              Not sent because the previous request failed.
                            </p>
                          )}
                        </div>
                      </details>
                    );
                  })}
                </div>
              </section>
            )}
          </>
        )}

        {!accounts && !loadError && <p className={styles.loading}>Loading active seed accounts…</p>}
        <footer className={styles.note}>
          Each prepared sequence uses fresh request IDs and randomly selected, active,
          unlisted seed accounts. The restricted-list scenario uses an active account
          whose owner is in the dev seed list. No result is simulated or saved as an
          AWS recording.
        </footer>
      </main>
    </Layout>
  );
}
