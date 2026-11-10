import {type FormEvent, useCallback, useEffect, useMemo, useState} from 'react';
import Layout from '@theme/Layout';
import {
  ActionResult,
  type ApiConsole,
  type ApiResult,
  Badge,
  ConnectionPanel,
  Gate,
  ResultPanel,
  Stat,
  consoleStyles as ui,
  decisionTone,
  formatDate,
  money,
  useApiConsole,
} from '@site/src/components/ApiConsole';
import styles from './api-pages.module.css';

type Action = 'APPROVE' | 'HOLD' | 'REJECT';
type Rule = {
  code: string;
  type: string;
  rn?: string;
  description?: string;
  enabled?: boolean;
  action: Action;
  opens_case?: boolean;
  score?: number;
  params?: Record<string, unknown>;
  rule_version?: number;
};
type Catalog = {version: number; created_at: string; author: string; rules: Rule[]};
type RuleChange = {rule: Rule; catalog_version: number};
type VersionSummary = {
  version: number;
  created_at: string;
  author: string;
  change: {operation?: string; code?: string | null; from_version?: number};
};
type VersionPage = {total: number; versions: VersionSummary[]};
type Side = {
  rules_version: string;
  decisions: Record<string, number>;
  cases: number;
  amount_usd: Record<string, string>;
};
type Simulation = {
  day: string;
  transactions: number;
  current: Side;
  candidate: Side;
  changed: number;
  changes: Record<string, number>;
  released_usd: string;
  stopped_usd: string;
  examples: {
    transaction_id: string;
    type: string;
    amount: string;
    currency: string;
    current: {decision: string; rules_triggered: string[]};
    candidate: {decision: string; rules_triggered: string[]};
  }[];
};

const ACTIONS: Action[] = ['APPROVE', 'HOLD', 'REJECT'];
const ALWAYS_ENABLED = 'default_timeout';
const FIXTURE_DAY = '2026-10-05';

export default function RulesApiPage() {
  const api = useApiConsole();
  const [tab, setTab] = useState<'catalog' | 'versions' | 'simulate'>('catalog');
  const [catalog, setCatalog] = useState<ApiResult<Catalog> | null>(null);

  const loadCatalog = useCallback(async () => {
    setCatalog(await api.call<Catalog>('GET', '/rules'));
  }, [api.call]);

  useEffect(() => {
    if (api.ready) void loadCatalog();
  }, [api.ready, loadCatalog]);

  const canWrite = api.role === 'gerente';
  const rules = catalog?.ok ? (catalog.body as Catalog).rules : [];

  return (
    <Layout title="Rules API" description="Create, version and activate the antifraud rules on AWS.">
      <main className={styles.page}>
        <header className={styles.hero}>
          <p className={styles.eyebrow}>Rules API · risk manager</p>
          <h1>Antifraud rules</h1>
          <p>
            The catalog the decision engine applies to every transaction (RF-03, RN-08). Every
            change is a new version and reaches the engine in about a second, without a
            deploy. Only the risk manager changes it; the analyst reads it.
          </p>
        </header>

        <ConnectionPanel
          api={api}
          purpose="The page talks to the rules API of AWS through API Gateway, signed in with Cognito. The LED asks /health every 15 seconds."
        />

        <Gate api={api}>
          {api.role !== 'gerente' && (
            <p className={ui.warning}>
              You are signed in as {api.role === 'analista' ? 'a fraud analyst' : 'a user without a group'}:
              the catalog is read only. The API answers 403 to any change.
            </p>
          )}
          <nav className={ui.tabs} aria-label="Rules API sections">
            {(
              [
                ['catalog', 'Catalog'],
                ['versions', 'Versions'],
                ['simulate', 'Simulate a change'],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={tab === id ? ui.activeTab : undefined}
                aria-pressed={tab === id}
                onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </nav>

          {tab === 'catalog' && (
            <CatalogView api={api} result={catalog} reload={loadCatalog} canWrite={canWrite} />
          )}
          {tab === 'versions' && (
            <VersionsView api={api} canWrite={canWrite} onActivated={loadCatalog} />
          )}
          {tab === 'simulate' && <SimulateView api={api} rules={rules} />}
        </Gate>
      </main>
    </Layout>
  );
}

function CatalogView({
  api,
  result,
  reload,
  canWrite,
}: {
  api: ApiConsole;
  result: ApiResult<Catalog> | null;
  reload: () => Promise<void>;
  canWrite: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [change, setChange] = useState<ApiResult<RuleChange> | null>(null);
  const catalog = result?.ok ? (result.body as Catalog) : null;

  const toggle = async (rule: Rule) => {
    const verb = rule.enabled === false ? 'enable' : 'disable';
    const answer = await api.call<RuleChange>('POST', `/rules/${rule.code}/${verb}`);
    setChange(answer);
    if (answer.ok) await reload();
  };

  const saved = async (answer: ApiResult<RuleChange>) => {
    setChange(answer);
    if (answer.ok) {
      setEditing(null);
      setCreating(false);
      await reload();
    }
  };

  const changeText = change?.ok
    ? `${(change.body as RuleChange).rule.code} saved: catalog version ${(change.body as RuleChange).catalog_version}.`
    : '';

  return (
    <ResultPanel
      result={result}
      title={catalog ? `Catalog · version ${catalog.version}` : 'Catalog'}
      actions={
        <>
          <button type="button" className={ui.ghost} onClick={() => void reload()}>
            Refresh
          </button>
          {canWrite && (
            <button type="button" className={ui.primary} onClick={() => setCreating(!creating)}>
              {creating ? 'Close' : 'New rule'}
            </button>
          )}
        </>
      }>
      {!result && <p className={ui.muted}>Loading the catalog…</p>}
      {catalog && (
        <>
          <div className={ui.stats}>
            <Stat label="Rules" value={catalog.rules.length} />
            <Stat label="Enabled" value={catalog.rules.filter((r) => r.enabled !== false).length} />
            <Stat label="Open a case" value={catalog.rules.filter((r) => r.opens_case).length} />
            <Stat label="Last change" value={catalog.author} small detail={formatDate(catalog.created_at)} />
          </div>
          <ActionResult result={change} success={changeText} />
          {creating && (
            <RuleForm
              api={api}
              rules={catalog.rules}
              onSaved={saved}
              onCancel={() => setCreating(false)}
            />
          )}
          <div className={ui.tableWrap}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Decision</th>
                  <th>Score</th>
                  <th>Parameters</th>
                  <th>Version</th>
                  <th>State</th>
                  {canWrite && <th />}
                </tr>
              </thead>
              <tbody>
                {catalog.rules.map((rule) => (
                  <RuleRow
                    key={rule.code}
                    rule={rule}
                    canWrite={canWrite}
                    editing={editing === rule.code}
                    onEdit={() => setEditing(editing === rule.code ? null : rule.code)}
                    onToggle={() => void toggle(rule)}
                    form={
                      <RuleForm
                        api={api}
                        rules={catalog.rules}
                        rule={rule}
                        onSaved={saved}
                        onCancel={() => setEditing(null)}
                      />
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </ResultPanel>
  );
}

function RuleRow({
  rule,
  canWrite,
  editing,
  onEdit,
  onToggle,
  form,
}: {
  rule: Rule;
  canWrite: boolean;
  editing: boolean;
  onEdit: () => void;
  onToggle: () => void;
  form: React.ReactNode;
}) {
  const enabled = rule.enabled !== false;
  return (
    <>
      <tr className={editing ? ui.selected : undefined}>
        <td>
          <strong>{rule.code}</strong>
          {rule.rn && <span className={ui.muted}> · {rule.rn}</span>}
          {rule.description && rule.description !== rule.code && (
            <div className={ui.muted}>{rule.description}</div>
          )}
        </td>
        <td>
          <Badge tone={decisionTone(rule.action)}>{rule.action}</Badge>
          {rule.opens_case && (
            <>
              {' '}
              <Badge tone="info">case</Badge>
            </>
          )}
        </td>
        <td>{rule.score ?? 0}</td>
        <td className={ui.mono}>
          {Object.entries(rule.params ?? {})
            .map(([key, value]) => `${key}: ${String(value)}`)
            .join(' · ') || '—'}
        </td>
        <td>v{rule.rule_version ?? 1}</td>
        <td>
          {canWrite && rule.code !== ALWAYS_ENABLED ? (
            <button
              type="button"
              className={styles.toggle}
              data-on={enabled}
              aria-pressed={enabled}
              onClick={onToggle}
              title={enabled ? 'Disable' : 'Enable'}>
              <span />
              {enabled ? 'On' : 'Off'}
            </button>
          ) : (
            <Badge tone={enabled ? 'success' : 'neutral'}>{enabled ? 'On' : 'Off'}</Badge>
          )}
        </td>
        {canWrite && (
          <td>
            <button type="button" className={ui.linkButton} onClick={onEdit}>
              {editing ? 'Close' : 'Edit'}
            </button>
          </td>
        )}
      </tr>
      {editing && (
        <tr>
          <td colSpan={7}>{form}</td>
        </tr>
      )}
    </>
  );
}

function paramValue(original: unknown, text: string): unknown {
  if (typeof original === 'number') return text === '' ? text : Number(text);
  if (typeof original === 'boolean') return text === 'true';
  return text;
}

/** Edit an existing rule (PUT) or create one of an existing type (POST). */
function RuleForm({
  api,
  rules,
  rule,
  onSaved,
  onCancel,
}: {
  api: ApiConsole;
  rules: Rule[];
  rule?: Rule;
  onSaved: (answer: ApiResult<RuleChange>) => void;
  onCancel: () => void;
}) {
  const types = useMemo(() => [...new Set(rules.map((r) => r.type))], [rules]);
  const [code, setCode] = useState('');
  const [type, setType] = useState(rule?.type ?? types[0] ?? '');
  const template = rule ?? rules.find((r) => r.type === type);
  const [description, setDescription] = useState(rule?.description ?? '');
  const [action, setAction] = useState<Action>(rule?.action ?? template?.action ?? 'HOLD');
  const [opensCase, setOpensCase] = useState(rule?.opens_case ?? false);
  const [score, setScore] = useState(String(rule?.score ?? 0));
  const [params, setParams] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const source = rule ?? rules.find((r) => r.type === type);
    setParams(
      Object.fromEntries(Object.entries(source?.params ?? {}).map(([k, v]) => [k, String(v)])),
    );
  }, [rule, rules, type]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    const typed = Object.fromEntries(
      Object.entries(params).map(([key, text]) => [key, paramValue(template?.params?.[key], text)]),
    );
    const body = {
      description,
      action,
      opens_case: opensCase,
      score: Number(score),
      params: typed,
    };
    const answer = rule
      ? await api.call<RuleChange>('PUT', `/rules/${rule.code}`, body)
      : await api.call<RuleChange>('POST', '/rules', {code, type, rn: template?.rn, ...body});
    setBusy(false);
    onSaved(answer);
  };

  return (
    <form className={ui.form} onSubmit={submit}>
      {!rule && (
        <>
          <label>
            Code
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="velocity_1h"
              pattern="[a-z][a-z0-9_]*"
              required
            />
          </label>
          <label>
            Type
            <select value={type} onChange={(event) => setType(event.target.value)}>
              {types
                .filter((t) => t !== ALWAYS_ENABLED)
                .map((t) => (
                  <option key={t}>{t}</option>
                ))}
            </select>
          </label>
        </>
      )}
      <label>
        Decision when it fires
        <select value={action} onChange={(event) => setAction(event.target.value as Action)}>
          {ACTIONS.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
      </label>
      <label>
        Risk score (0 to 100)
        <input
          type="number"
          min={0}
          max={100}
          value={score}
          onChange={(event) => setScore(event.target.value)}
        />
      </label>
      <label className={ui.checkbox}>
        <input
          type="checkbox"
          checked={opensCase}
          onChange={(event) => setOpensCase(event.target.checked)}
        />
        Opens a case
      </label>
      {Object.entries(params).map(([key, value]) => (
        <label key={key}>
          {key}
          <input
            value={value}
            onChange={(event) => setParams({...params, [key]: event.target.value})}
            inputMode={typeof template?.params?.[key] === 'number' ? 'decimal' : undefined}
          />
        </label>
      ))}
      <label className={ui.wide}>
        Description
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      <div className={ui.formActions}>
        <button type="submit" className={ui.primary} disabled={busy}>
          {busy ? 'Saving…' : rule ? 'Save as a new version' : 'Create rule'}
        </button>
        <button type="button" className={ui.ghost} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function VersionsView({
  api,
  canWrite,
  onActivated,
}: {
  api: ApiConsole;
  canWrite: boolean;
  onActivated: () => Promise<void>;
}) {
  const [page, setPage] = useState<ApiResult<VersionPage> | null>(null);
  const [shown, setShown] = useState<ApiResult<Catalog> | null>(null);
  const [activated, setActivated] = useState<ApiResult<Catalog> | null>(null);

  const load = useCallback(async () => {
    setPage(await api.call<VersionPage>('GET', '/rules/versions?limit=50'));
  }, [api.call]);

  useEffect(() => {
    void load();
  }, [load]);

  const show = async (version: number) => {
    setShown(await api.call<Catalog>('GET', `/rules/versions/${version}`));
  };

  const activate = async (version: number) => {
    if (!window.confirm(`Make the rules of version ${version} the current catalog? It writes a new version; history is never rewritten.`)) {
      return;
    }
    const answer = await api.call<Catalog>('POST', `/rules/versions/${version}/activate`);
    setActivated(answer);
    if (answer.ok) {
      await Promise.all([load(), onActivated()]);
    }
  };

  const versions = page?.ok ? (page.body as VersionPage).versions : [];
  const latest = versions[0]?.version;
  const shownCatalog = shown?.ok ? (shown.body as Catalog) : null;

  return (
    <>
      <ResultPanel
        result={page}
        title={page?.ok ? `Versions · ${(page.body as VersionPage).total}` : 'Versions'}
        actions={
          <button type="button" className={ui.ghost} onClick={() => void load()}>
            Refresh
          </button>
        }>
        <p className={ui.muted}>
          Append-only (RN-08): each decision records the version that decided it. Activating an
          old version writes a new one with its rules.
        </p>
        <ActionResult
          result={activated}
          success={
            activated?.ok ? `Now at version ${(activated.body as Catalog).version}.` : ''
          }
        />
        <div className={ui.tableWrap}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th>Version</th>
                <th>When</th>
                <th>Who</th>
                <th>Change</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr
                  key={version.version}
                  className={`${ui.clickable} ${shownCatalog?.version === version.version ? ui.selected : ''}`}
                  onClick={() => void show(version.version)}>
                  <td>
                    <strong>v{version.version}</strong>
                    {version.version === latest && (
                      <>
                        {' '}
                        <Badge tone="success">current</Badge>
                      </>
                    )}
                  </td>
                  <td>{formatDate(version.created_at)}</td>
                  <td>{version.author}</td>
                  <td>
                    {version.change.operation ?? 'initial'}
                    {version.change.code ? ` · ${version.change.code}` : ''}
                    {version.change.from_version !== undefined
                      ? ` · from v${version.change.from_version}`
                      : ''}
                  </td>
                  <td>
                    {canWrite && version.version !== latest && (
                      <button
                        type="button"
                        className={ui.linkButton}
                        onClick={(event) => {
                          event.stopPropagation();
                          void activate(version.version);
                        }}>
                        Activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ResultPanel>
      {shown && (
        <ResultPanel
          result={shown}
          title={shownCatalog ? `Version ${shownCatalog.version}` : 'Version'}>
          {shownCatalog && (
            <div className={styles.ruleGrid}>
              {shownCatalog.rules.map((rule) => (
                <article key={rule.code} className={styles.ruleCard} data-off={rule.enabled === false}>
                  <header>
                    <strong>{rule.code}</strong>
                    <Badge tone={decisionTone(rule.action)}>{rule.action}</Badge>
                  </header>
                  <p className={ui.muted}>
                    {rule.enabled === false ? 'Disabled' : 'Enabled'} · score {rule.score ?? 0} · rule
                    v{rule.rule_version ?? 1}
                  </p>
                  <p className={ui.mono}>
                    {Object.entries(rule.params ?? {})
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(' · ') || '—'}
                  </p>
                </article>
              ))}
            </div>
          )}
        </ResultPanel>
      )}
    </>
  );
}

/** HU-24: replay one day with the current catalog and with one changed rule. */
function SimulateView({api, rules}: {api: ApiConsole; rules: Rule[]}) {
  const editable = rules.filter((r) => r.code !== ALWAYS_ENABLED);
  const [day, setDay] = useState(FIXTURE_DAY);
  const [code, setCode] = useState(editable[0]?.code ?? '');
  const rule = rules.find((r) => r.code === code);
  const [enabled, setEnabled] = useState(true);
  const [action, setAction] = useState<Action>('HOLD');
  const [params, setParams] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ApiResult<Simulation> | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!rule) return;
    setEnabled(rule.enabled !== false);
    setAction(rule.action);
    setParams(Object.fromEntries(Object.entries(rule.params ?? {}).map(([k, v]) => [k, String(v)])));
  }, [rule]);

  const run = async (event: FormEvent) => {
    event.preventDefault();
    if (!rule) return;
    setBusy(true);
    const changed: Rule = {
      ...rule,
      enabled,
      action,
      params: Object.fromEntries(
        Object.entries(params).map(([k, text]) => [k, paramValue(rule.params?.[k], text)]),
      ),
    };
    const candidate = rules.map((r) => (r.code === rule.code ? changed : r));
    setResult(await api.call<Simulation>('POST', '/rules/simulations', {day, candidate}));
    setBusy(false);
  };

  const simulation = result?.ok ? (result.body as Simulation) : null;

  return (
    <ResultPanel result={result} title="Simulate a change (HU-24)">
      <p className={ui.muted}>
        Replays one day of decisions from the data lake with the current catalog and with your
        change, and compares them. It never writes a rule, a version or the cache, so the analyst
        may run it too.
      </p>
      <form className={ui.form} onSubmit={run}>
        <label>
          Day (UTC)
          <input type="date" value={day} onChange={(event) => setDay(event.target.value)} required />
        </label>
        <label>
          Rule
          <select value={code} onChange={(event) => setCode(event.target.value)}>
            {editable.map((r) => (
              <option key={r.code}>{r.code}</option>
            ))}
          </select>
        </label>
        <label>
          Decision
          <select value={action} onChange={(event) => setAction(event.target.value as Action)}>
            {ACTIONS.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <label className={ui.checkbox}>
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          Enabled
        </label>
        {Object.entries(params).map(([key, value]) => (
          <label key={key}>
            {key}
            <input value={value} onChange={(event) => setParams({...params, [key]: event.target.value})} />
          </label>
        ))}
        <div className={ui.formActions}>
          <button type="submit" className={ui.primary} disabled={busy || !rule}>
            {busy ? 'Replaying…' : 'Run the simulation'}
          </button>
        </div>
      </form>
      {simulation && (
        <>
          <div className={ui.stats}>
            <Stat label="Transactions" value={simulation.transactions} />
            <Stat label="Decisions that change" value={simulation.changed} />
            <Stat label="Released (USD)" value={money(simulation.released_usd)} />
            <Stat label="Stopped (USD)" value={money(simulation.stopped_usd)} />
          </div>
          <div className={styles.compare}>
            <SideCard title={`Current · v${simulation.current.rules_version}`} side={simulation.current} />
            <SideCard title="With your change" side={simulation.candidate} />
          </div>
          {Object.keys(simulation.changes).length > 0 && (
            <p>
              {Object.entries(simulation.changes).map(([key, count]) => (
                <span key={key} className={styles.change}>
                  {key.replace('->', ' → ')} <strong>{count}</strong>
                </span>
              ))}
            </p>
          )}
          {simulation.examples.length > 0 && (
            <div className={ui.tableWrap}>
              <table className={ui.table}>
                <thead>
                  <tr>
                    <th>Transaction</th>
                    <th>Amount</th>
                    <th>Now</th>
                    <th>With the change</th>
                  </tr>
                </thead>
                <tbody>
                  {simulation.examples.map((example) => (
                    <tr key={example.transaction_id}>
                      <td>
                        <span className={ui.mono}>{example.transaction_id.slice(0, 8)}</span> ·{' '}
                        {example.type}
                      </td>
                      <td>{money(example.amount, example.currency)}</td>
                      <td>
                        <Badge tone={decisionTone(example.current.decision)}>
                          {example.current.decision}
                        </Badge>
                      </td>
                      <td>
                        <Badge tone={decisionTone(example.candidate.decision)}>
                          {example.candidate.decision}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </ResultPanel>
  );
}

function SideCard({title, side}: {title: string; side: Side}) {
  return (
    <article className={styles.side}>
      <h3>{title}</h3>
      {ACTIONS.map((decision) => (
        <p key={decision}>
          <Badge tone={decisionTone(decision)}>{decision}</Badge>{' '}
          <strong>{side.decisions[decision] ?? 0}</strong>{' '}
          <span className={ui.muted}>· USD {money(side.amount_usd[decision] ?? '0')}</span>
        </p>
      ))}
      <p className={ui.muted}>Cases opened: {side.cases}</p>
    </article>
  );
}
