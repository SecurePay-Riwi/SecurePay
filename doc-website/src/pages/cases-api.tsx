import {type FormEvent, Fragment, useCallback, useEffect, useState} from 'react';
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

type CaseStatus = 'OPEN' | 'ESCALATED' | 'RESOLVED';
type CaseSummary = {
  id: string;
  transaction_id: string;
  account_id: string;
  status: CaseStatus;
  decision: string;
  rules_triggered: string[];
  risk_score: number;
  amount: string;
  currency: string;
  amount_usd: string | null;
  usd_rate?: string | null;
  rate_date?: string | null;
  assignee: string | null;
  created_at: string;
  due_at: string;
  minutes_left: number | null;
};
type CaseEvent = {id: number; type: string; actor: string; at: string; data: Record<string, unknown>};
type CaseDetail = CaseSummary & {
  decision_reason?: string | null;
  rules_version?: string | null;
  rule_versions?: Record<string, number> | null;
  transaction_date?: string | null;
  transaction?: Record<string, unknown> | null;
  escalated_at?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  outcome?: string | null;
  final_decision?: string | null;
  resolution_note?: string | null;
  evidence_key?: string | null;
  events: CaseEvent[];
};
type Page<T> = {items: T[]; total: number; page?: number; size?: number};
type Sender = {
  account_id: string;
  transfers: number;
  amount_usd: string | null;
  first_at: string;
  last_at: string;
  open_cases: number;
};
type Senders = {
  minutes: number;
  senders: Sender[];
  total_senders: number;
  received_usd: string | null;
  case_amount_usd: string | null;
  case_vs_received_pct: string | null;
};
type AccountTx = {
  transaction_id: string;
  direction: 'IN' | 'OUT';
  counterparty_account_id: string | null;
  type: string;
  amount: string;
  currency: string;
  amount_usd: string | null;
  decision: string;
  rules_triggered: string[];
  risk_score: number;
  transaction_date: string;
};
type Related = {account_id: string; device_id: string; last_seen: string; open_cases: number};
type Suspicious = {
  case_id: string;
  account_id: string;
  pattern: string;
  amount: string;
  currency: string;
  amount_usd: string | null;
  status: string;
  outcome: string | null;
  created_at: string;
};
type SuspiciousReport = {items: Suspicious[]; total: number; message?: string | null};
type ListReport = {
  id: string;
  case_id: string;
  account_id: string;
  document: string;
  list_type: string;
  matched_at: string;
  notified_at: string | null;
};
type Difference = {
  id: string;
  run_day: string;
  partner: string;
  type: string;
  reference: string;
  currency: string | null;
  pagoseguro_amount: string | null;
  partner_amount: string | null;
  amount_difference: string | null;
  status: string;
  age_days: number;
  resolved_by?: string | null;
  resolution_note?: string | null;
};
type Aging = {total: number; ranges: {range: string; count: number; by_type: Record<string, number>}[]};
type Run = {
  run_day: string;
  status: string;
  files_read: number | null;
  records_read: number | null;
  rows_rejected: number | null;
  matched: number | null;
  differences: number | null;
  error: string | null;
};

type Tab = 'inbox' | 'account' | 'escalated' | 'reports' | 'reconciliation';

const ANALYST_TABS: [Tab, string][] = [
  ['inbox', 'Case inbox'],
  ['account', 'Account lookup'],
];
const MANAGER_TABS: [Tab, string][] = [
  ['escalated', 'Escalated'],
  ['reports', 'Compliance reports'],
  ['reconciliation', 'Reconciliation'],
];

export default function CasesApiPage() {
  const api = useApiConsole();
  const [tab, setTab] = useState<Tab>('inbox');
  const manager = api.role === 'gerente';
  const tabs = manager ? [...ANALYST_TABS, ...MANAGER_TABS] : ANALYST_TABS;
  const [account, setAccount] = useState('');

  useEffect(() => {
    if (!manager && !ANALYST_TABS.some(([id]) => id === tab)) setTab('inbox');
  }, [manager, tab]);

  const openAccount = (id: string) => {
    setAccount(id);
    setTab('account');
  };

  return (
    <Layout title="Cases API" description="The analysts' case inbox and the manager's views, on AWS.">
      <main className={styles.page}>
        <header className={styles.hero}>
          <p className={styles.eyebrow}>Cases API · analysts and manager</p>
          <h1>Fraud cases</h1>
          <p>
            Every HOLD that opens a case lands here, the riskiest first, with the minutes left
            before it escalates (RN-09). The analyst takes it, looks at the account and resolves
            it; the risk manager also follows what escalated, the compliance reports and the
            reconciliation.
          </p>
        </header>

        <ConnectionPanel
          api={api}
          purpose="The page talks to the cases API of AWS through API Gateway, signed in with Cognito. Your e-mail becomes the actor of every assignment and resolution."
        />

        <Gate api={api}>
          {!api.role && (
            <p className={ui.warning}>
              This user is in no Cognito group: put it in analista or gerente to see the views of
              that role.
            </p>
          )}
          <nav className={ui.tabs} aria-label="Cases API sections">
            {tabs.map(([id, label]) => (
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

          {tab === 'inbox' && <InboxView key="inbox" api={api} onAccount={openAccount} />}
          {tab === 'account' && <AccountView api={api} initial={account} />}
          {tab === 'escalated' && manager && (
            <InboxView key="escalated" api={api} onAccount={openAccount} escalated />
          )}
          {tab === 'reports' && manager && <ReportsView api={api} />}
          {tab === 'reconciliation' && manager && <ReconciliationView api={api} />}
        </Gate>
      </main>
    </Layout>
  );
}

/* ---------- Inbox and case detail (HU-26, HU-27, HU-30) ---------- */

function InboxView({
  api,
  onAccount,
  escalated = false,
}: {
  api: ApiConsole;
  onAccount: (id: string) => void;
  escalated?: boolean;
}) {
  const [status, setStatus] = useState<'' | CaseStatus>(escalated ? 'ESCALATED' : '');
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<ApiResult<Page<CaseSummary>> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const size = 20;

  const load = useCallback(async () => {
    const query = new URLSearchParams({page: String(page), size: String(size)});
    if (status) query.set('status', status);
    if (mine && api.session) query.set('assignee', api.session.email);
    setResult(await api.call<Page<CaseSummary>>('GET', `/cases?${query}`));
  }, [api.call, api.session, mine, page, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const data = result?.ok ? (result.body as Page<CaseSummary>) : null;
  const items = data?.items ?? [];
  const overdue = items.filter((c) => c.minutes_left !== null && c.minutes_left < 0).length;
  const pages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;

  return (
    <>
      <ResultPanel
        result={result}
        title={escalated ? 'Escalated cases' : 'Case inbox'}
        actions={
          <button type="button" className={ui.ghost} onClick={() => void load()}>
            Refresh
          </button>
        }>
        <div className={ui.toolbar}>
          {!escalated && (
            <label>
              State
              <select
                value={status}
                onChange={(e) => {
                  setPage(1);
                  setStatus(e.target.value as '' | CaseStatus);
                }}>
                <option value="">Pending (open and escalated)</option>
                <option value="OPEN">Open</option>
                <option value="ESCALATED">Escalated</option>
                <option value="RESOLVED">Resolved</option>
              </select>
            </label>
          )}
          <label className={ui.checkbox}>
            <input
              type="checkbox"
              checked={mine}
              onChange={(e) => {
                setPage(1);
                setMine(e.target.checked);
              }}
            />
            Only mine
          </label>
        </div>

        {data && (
          <div className={ui.stats}>
            <Stat label="Cases" value={data.total} />
            <Stat label="Overdue on this page" value={overdue} detail="more than 4 hours (RN-09)" />
            <Stat
              label="Unassigned on this page"
              value={items.filter((c) => !c.assignee).length}
            />
          </div>
        )}

        {data && items.length === 0 && <p className={ui.empty}>No cases here.</p>}
        {items.length > 0 && (
          <div className={ui.tableWrap}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th>Risk</th>
                  <th>Rules</th>
                  <th>Amount</th>
                  <th>State</th>
                  <th>Time left</th>
                  <th>Assignee</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr
                    key={c.id}
                    className={`${ui.clickable} ${selected === c.id ? ui.selected : ''}`}
                    onClick={() => setSelected(selected === c.id ? null : c.id)}>
                    <td>
                      <strong>{c.risk_score}</strong>
                    </td>
                    <td>{c.rules_triggered.join(' + ') || '—'}</td>
                    <td>
                      {money(c.amount, c.currency)}
                      {c.currency !== 'USD' && c.amount_usd && (
                        <div className={ui.muted}>USD {money(c.amount_usd)}</div>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={c.status} />
                    </td>
                    <td>
                      <MinutesLeft minutes={c.minutes_left} />
                    </td>
                    <td>{c.assignee ?? <span className={ui.muted}>nobody</span>}</td>
                    <td>{formatDate(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className={ui.toolbar}>
            <button
              type="button"
              className={ui.ghost}
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span className={ui.muted}>
              Page {page} of {pages}
            </span>
            <button
              type="button"
              className={ui.ghost}
              disabled={page >= pages}
              onClick={() => setPage(page + 1)}>
              Next
            </button>
          </div>
        )}
      </ResultPanel>

      {selected && (
        <CaseView
          key={selected}
          api={api}
          caseId={selected}
          onChanged={load}
          onAccount={onAccount}
        />
      )}
    </>
  );
}

function CaseView({
  api,
  caseId,
  onChanged,
  onAccount,
}: {
  api: ApiConsole;
  caseId: string;
  onChanged: () => Promise<void>;
  onAccount: (id: string) => void;
}) {
  const [result, setResult] = useState<ApiResult<CaseDetail> | null>(null);
  const [senders, setSenders] = useState<ApiResult<Senders> | null>(null);
  const [change, setChange] = useState<ApiResult<CaseDetail> | null>(null);
  const [assignee, setAssignee] = useState('');
  const [outcome, setOutcome] = useState<'FRAUD' | 'LEGITIMATE'>('FRAUD');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setResult(await api.call<CaseDetail>('GET', `/cases/${caseId}`));
  }, [api.call, caseId]);

  useEffect(() => {
    void load();
  }, [load]);

  const detail = result?.ok ? (result.body as CaseDetail) : null;
  const resolved = detail?.status === 'RESOLVED';
  const mule = detail?.rules_triggered.includes('mule');

  useEffect(() => {
    if (mule) void api.call<Senders>('GET', `/cases/${caseId}/senders`).then(setSenders);
  }, [api.call, caseId, mule]);

  const run = async (method: 'PUT' | 'POST', path: string, body: unknown) => {
    setBusy(true);
    const answer = await api.call<CaseDetail>(method, path, body);
    setChange(answer);
    if (answer.ok) {
      setResult({...answer, method: 'GET', path: `/cases/${caseId}`, requestBody: undefined});
      await onChanged();
    }
    setBusy(false);
  };

  const assign = (event: FormEvent) => {
    event.preventDefault();
    void run('PUT', `/cases/${caseId}/assignee`, {assignee: assignee.trim() || api.session?.email});
  };

  const resolve = (event: FormEvent) => {
    event.preventDefault();
    if (!window.confirm(`Resolve this case as ${outcome}? A resolved case cannot change again.`)) return;
    void run('POST', `/cases/${caseId}/resolution`, {outcome, note: note.trim()});
  };

  const tx = detail?.transaction ?? {};

  return (
    <ResultPanel
      result={result}
      title={detail ? `Case · ${detail.rules_triggered.join(' + ')}` : 'Case'}
      actions={detail && <StatusBadge status={detail.status} />}>
      {detail && (
        <>
          {detail.decision_reason && <p className={ui.help}>{detail.decision_reason}</p>}
          <div className={styles.detail}>
            <article className={styles.card}>
              <h3>Transaction</h3>
              <dl className={styles.facts}>
                <dt>Type</dt>
                <dd>{String(tx.type ?? '—')}</dd>
                <dt>Amount</dt>
                <dd>
                  {money(detail.amount, detail.currency)}
                  {detail.amount_usd && detail.currency !== 'USD' && (
                    <span className={ui.muted}>
                      {' '}
                      · USD {money(detail.amount_usd)} at {detail.usd_rate} ({detail.rate_date})
                    </span>
                  )}
                </dd>
                <dt>Engine</dt>
                <dd>
                  <Badge tone={decisionTone(detail.decision)}>{detail.decision}</Badge> · risk{' '}
                  {detail.risk_score} · catalog v{detail.rules_version ?? '—'}
                </dd>
                <dt>Account</dt>
                <dd>
                  <button
                    type="button"
                    className={ui.linkButton}
                    onClick={() => onAccount(detail.account_id)}>
                    <span className={ui.mono}>{detail.account_id}</span>
                  </button>
                </dd>
                {typeof tx.destination_account_id === 'string' && (
                  <>
                    <dt>To</dt>
                    <dd>
                      <button
                        type="button"
                        className={ui.linkButton}
                        onClick={() => onAccount(String(tx.destination_account_id))}>
                        <span className={ui.mono}>{String(tx.destination_account_id)}</span>
                      </button>
                    </dd>
                  </>
                )}
                <dt>When</dt>
                <dd>{formatDate(detail.transaction_date)}</dd>
                <dt>Due</dt>
                <dd>
                  {formatDate(detail.due_at)} · <MinutesLeft minutes={detail.minutes_left} />
                </dd>
                <dt>Assignee</dt>
                <dd>{detail.assignee ?? 'nobody'}</dd>
                {resolved && (
                  <>
                    <dt>Outcome</dt>
                    <dd>
                      <Badge tone={detail.outcome === 'FRAUD' ? 'danger' : 'success'}>
                        {detail.outcome}
                      </Badge>{' '}
                      → {detail.final_decision} by {detail.resolved_by}
                    </dd>
                    <dt>Note</dt>
                    <dd>{detail.resolution_note}</dd>
                    <dt>Evidence</dt>
                    <dd className={ui.mono}>{detail.evidence_key ?? 'being archived'}</dd>
                  </>
                )}
              </dl>
            </article>
            <article className={styles.card}>
              <h3>History</h3>
              <ol className={styles.timeline}>
                {detail.events.map((event) => (
                  <li key={event.id}>
                    <strong>{event.type}</strong> · {event.actor}
                    <div className={ui.muted}>{formatDate(event.at)}</div>
                    <EventData event={event} />
                  </li>
                ))}
              </ol>
            </article>
          </div>

          {!resolved && (
            <div className={styles.detail}>
              <form className={`${styles.card} ${ui.form}`} onSubmit={assign}>
                <h3 className={ui.wide}>Assign</h3>
                <label className={ui.wide}>
                  Analyst
                  <input
                    value={assignee}
                    onChange={(e) => setAssignee(e.target.value)}
                    placeholder={api.session?.email ?? 'analyst e-mail'}
                  />
                </label>
                <div className={ui.formActions}>
                  <button type="submit" className={ui.primary} disabled={busy}>
                    {assignee.trim() ? 'Assign' : 'Take it'}
                  </button>
                </div>
              </form>
              <form className={`${styles.card} ${ui.form}`} onSubmit={resolve}>
                <h3 className={ui.wide}>Resolve</h3>
                <label>
                  Outcome
                  <select
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value as 'FRAUD' | 'LEGITIMATE')}>
                    <option value="FRAUD">Fraud → REJECT</option>
                    <option value="LEGITIMATE">Legitimate → APPROVE</option>
                  </select>
                </label>
                <label className={ui.wide}>
                  Note
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    maxLength={2000}
                    required
                    placeholder="What you checked and why"
                  />
                </label>
                <div className={ui.formActions}>
                  <button
                    type="submit"
                    className={outcome === 'FRAUD' ? ui.danger : ui.primary}
                    disabled={busy || !note.trim()}>
                    Resolve
                  </button>
                </div>
              </form>
            </div>
          )}
          <ActionResult result={change} success="Case updated." />

          {mule && senders && (
            <>
              <h3 style={{marginTop: '1.25rem'}}>Who sent the money (mule rule)</h3>
              {senders.ok ? (
                <SendersTable data={senders.body as Senders} onAccount={onAccount} />
              ) : (
                <p className={ui.error}>{senders.error}</p>
              )}
            </>
          )}
        </>
      )}
    </ResultPanel>
  );
}

function SendersTable({data, onAccount}: {data: Senders; onAccount: (id: string) => void}) {
  return (
    <>
      <div className={ui.stats}>
        <Stat label="Senders" value={data.total_senders} detail={`in the ${data.minutes} min before`} />
        <Stat label="Received" value={`USD ${money(data.received_usd)}`} />
        <Stat
          label="Withdrawn of it"
          value={data.case_vs_received_pct ? `${data.case_vs_received_pct} %` : '—'}
        />
      </div>
      <div className={ui.tableWrap}>
        <table className={ui.table}>
          <thead>
            <tr>
              <th>Sender</th>
              <th>Transfers</th>
              <th>USD</th>
              <th>Open cases</th>
              <th>Last</th>
            </tr>
          </thead>
          <tbody>
            {data.senders.map((s) => (
              <tr key={s.account_id}>
                <td>
                  <button type="button" className={ui.linkButton} onClick={() => onAccount(s.account_id)}>
                    <span className={ui.mono}>{s.account_id.slice(0, 8)}…</span>
                  </button>
                </td>
                <td>{s.transfers}</td>
                <td>{money(s.amount_usd)}</td>
                <td>{s.open_cases > 0 ? <Badge tone="warning">{s.open_cases}</Badge> : 0}</td>
                <td>{formatDate(s.last_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function EventData({event}: {event: CaseEvent}) {
  const data = event.data ?? {};
  if (event.type === 'ASSIGNED') {
    return <div className={ui.muted}>{`${data.from ?? 'nobody'} → ${data.to}`}</div>;
  }
  if (event.type === 'RESOLVED') {
    return <div className={ui.muted}>{`${data.outcome} · ${data.note ?? ''}`}</div>;
  }
  if (event.type === 'EVIDENCE_ARCHIVED') {
    return <div className={ui.mono}>{String(data.key ?? '')}</div>;
  }
  return null;
}

function StatusBadge({status}: {status: string}) {
  const tone = status === 'ESCALATED' ? 'danger' : status === 'OPEN' ? 'warning' : 'success';
  return <Badge tone={tone}>{status}</Badge>;
}

function MinutesLeft({minutes}: {minutes: number | null}) {
  if (minutes === null) return <span className={ui.muted}>—</span>;
  const late = minutes < 0;
  const value = Math.abs(minutes);
  const text = value >= 60 ? `${Math.floor(value / 60)} h ${value % 60} min` : `${value} min`;
  return (
    <span className={styles.due} data-late={late}>
      {late ? `${text} late` : text}
    </span>
  );
}

/* ---------- Account lookup (HU-28, HU-29) ---------- */

function AccountView({api, initial}: {api: ApiConsole; initial: string}) {
  const [account, setAccount] = useState(initial);
  const [days, setDays] = useState(30);
  const [history, setHistory] = useState<ApiResult<Page<AccountTx>> | null>(null);
  const [related, setRelated] = useState<ApiResult<Page<Related>> | null>(null);

  const load = useCallback(
    async (id: string) => {
      if (!id.trim()) return;
      const [h, r] = await Promise.all([
        api.call<Page<AccountTx>>('GET', `/accounts/${id.trim()}/transactions?days=${days}&size=50`),
        api.call<Page<Related>>('GET', `/accounts/${id.trim()}/related-accounts?days=${days}`),
      ]);
      setHistory(h);
      setRelated(r);
    },
    [api.call, days],
  );

  useEffect(() => {
    if (initial) {
      setAccount(initial);
      void load(initial);
    }
    // Only when another view sends an account.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void load(account);
  };

  const tx = history?.ok ? (history.body as Page<AccountTx>) : null;
  const rel = related?.ok ? (related.body as Page<Related>) : null;

  return (
    <>
      <form className={ui.toolbar} onSubmit={submit}>
        <label style={{flex: 1, minWidth: '16rem'}}>
          Account id
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            placeholder="5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42"
            spellCheck={false}
          />
        </label>
        <label>
          Days
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className={ui.primary} disabled={!account.trim()}>
          Look up
        </button>
      </form>

      {history && (
        <ResultPanel result={history} title="Transactions">
          {tx && tx.items.length === 0 && (
            <p className={ui.empty}>No transactions in the last {days} days.</p>
          )}
          {tx && tx.items.length > 0 && (
            <>
              <div className={ui.stats}>
                <Stat label="Transactions" value={tx.total} />
                <Stat label="In" value={tx.items.filter((t) => t.direction === 'IN').length} />
                <Stat label="Out" value={tx.items.filter((t) => t.direction === 'OUT').length} />
                <Stat
                  label="Held or rejected"
                  value={tx.items.filter((t) => t.decision !== 'APPROVE').length}
                />
              </div>
              <div className={ui.tableWrap}>
                <table className={ui.table}>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th></th>
                      <th>Type</th>
                      <th>Amount</th>
                      <th>Decision</th>
                      <th>Rules</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tx.items.map((t) => (
                      <tr key={`${t.transaction_id}-${t.direction}`}>
                        <td>{formatDate(t.transaction_date)}</td>
                        <td>
                          <Badge tone={t.direction === 'IN' ? 'info' : 'neutral'}>{t.direction}</Badge>
                        </td>
                        <td>{t.type}</td>
                        <td>{money(t.amount, t.currency)}</td>
                        <td>
                          <Badge tone={decisionTone(t.decision)}>{t.decision}</Badge>
                        </td>
                        <td className={ui.muted}>{t.rules_triggered.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </ResultPanel>
      )}

      {related && (
        <ResultPanel result={related} title="Accounts on the same devices">
          {rel && rel.items.length === 0 && (
            <p className={ui.empty}>No other account used its devices.</p>
          )}
          {rel && rel.items.length > 0 && (
            <div className={ui.tableWrap}>
              <table className={ui.table}>
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Device</th>
                    <th>Last seen</th>
                    <th>Open cases</th>
                  </tr>
                </thead>
                <tbody>
                  {rel.items.map((r) => (
                    <tr key={`${r.account_id}-${r.device_id}`}>
                      <td>
                        <button
                          type="button"
                          className={ui.linkButton}
                          onClick={() => {
                            setAccount(r.account_id);
                            void load(r.account_id);
                          }}>
                          <span className={ui.mono}>{r.account_id}</span>
                        </button>
                      </td>
                      <td className={ui.mono}>{r.device_id.slice(0, 8)}…</td>
                      <td>{formatDate(r.last_seen)}</td>
                      <td>{r.open_cases > 0 ? <Badge tone="warning">{r.open_cases}</Badge> : 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ResultPanel>
      )}
    </>
  );
}

/* ---------- Manager: compliance (HU-34, HU-35) ---------- */

function isoDay(offsetDays: number): string {
  const day = new Date(Date.now() + offsetDays * 86_400_000);
  return day.toISOString().slice(0, 10);
}

function ReportsView({api}: {api: ApiConsole}) {
  const [from, setFrom] = useState(isoDay(-30));
  const [to, setTo] = useState(isoDay(0));
  const [suspicious, setSuspicious] = useState<ApiResult<SuspiciousReport> | null>(null);
  const [listed, setListed] = useState<ApiResult<Page<ListReport>> | null>(null);
  const [csv, setCsv] = useState<ApiResult | null>(null);

  const load = useCallback(async () => {
    // The list reports take times, `to` excluded: up to the end of the last day.
    const end = new Date(Date.parse(`${to}T00:00:00Z`) + 86_400_000).toISOString();
    const [s, l] = await Promise.all([
      api.call<SuspiciousReport>('GET', `/reports/suspicious?from=${from}&to=${to}`),
      api.call<Page<ListReport>>(
        'GET',
        `/compliance/restricted-list-reports?from=${from}T00:00:00Z&to=${encodeURIComponent(end)}&size=100`,
      ),
    ]);
    setSuspicious(s);
    setListed(l);
  }, [api.call, from, to]);

  useEffect(() => {
    void load();
    // First load only; the button reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const download = async () => {
    const answer = await api.call('GET', `/reports/suspicious?from=${from}&to=${to}&format=csv`);
    setCsv(answer);
    if (!answer.ok || typeof answer.body !== 'string') return;
    const url = URL.createObjectURL(new Blob([answer.body], {type: 'text/csv'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = `suspicious-${from}-${to}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const report = suspicious?.ok ? (suspicious.body as SuspiciousReport) : null;
  const reports = listed?.ok ? (listed.body as Page<ListReport>) : null;
  const byPattern = new Map<string, number>();
  for (const item of report?.items ?? []) {
    byPattern.set(item.pattern, (byPattern.get(item.pattern) ?? 0) + 1);
  }
  const top = Math.max(1, ...byPattern.values());

  return (
    <>
      <form
        className={ui.toolbar}
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}>
        <label>
          From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button type="submit" className={ui.primary}>
          Show
        </button>
        <span className={ui.muted}>At most 31 days, both included (UTC).</span>
      </form>

      <ResultPanel
        result={suspicious}
        title="Suspicious operations"
        actions={
          <button type="button" className={ui.ghost} onClick={() => void download()}>
            Download CSV
          </button>
        }>
        {csv && !csv.ok && <p className={ui.error}>{csv.error}</p>}
        {report && report.items.length === 0 && (
          <p className={ui.empty}>{report.message ?? 'No cases in this period.'}</p>
        )}
        {report && report.items.length > 0 && (
          <>
            <div className={ui.stats}>
              <Stat label="Cases" value={report.total} />
              <Stat
                label="Fraud confirmed"
                value={report.items.filter((i) => i.outcome === 'FRAUD').length}
              />
              <Stat
                label="USD involved"
                value={money(
                  String(report.items.reduce((sum, i) => sum + Number(i.amount_usd ?? 0), 0)),
                )}
                small
              />
            </div>
            <div className={styles.card} style={{marginTop: '1rem'}}>
              <h3>By pattern</h3>
              {[...byPattern.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([pattern, count]) => (
                  <div key={pattern} style={{marginBottom: '0.5rem'}}>
                    <span>{pattern}</span> <strong>{count}</strong>
                    <div className={styles.bar}>
                      <span style={{width: `${(count / top) * 100}%`}} />
                    </div>
                  </div>
                ))}
            </div>
            <div className={ui.tableWrap}>
              <table className={ui.table}>
                <thead>
                  <tr>
                    <th>Opened</th>
                    <th>Pattern</th>
                    <th>Amount</th>
                    <th>State</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {report.items.map((i) => (
                    <tr key={i.case_id}>
                      <td>{formatDate(i.created_at)}</td>
                      <td>{i.pattern}</td>
                      <td>
                        {money(i.amount, i.currency)}
                        {i.currency !== 'USD' && i.amount_usd && (
                          <div className={ui.muted}>USD {money(i.amount_usd)}</div>
                        )}
                      </td>
                      <td>
                        <StatusBadge status={i.status} />
                      </td>
                      <td>{i.outcome ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </ResultPanel>

      <ResultPanel result={listed} title="Restricted list reports (RN-06)">
        {reports && reports.items.length === 0 && (
          <p className={ui.empty}>Nobody on the restricted list moved money in this period.</p>
        )}
        {reports && reports.items.length > 0 && (
          <div className={ui.tableWrap}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th>Matched</th>
                  <th>Document</th>
                  <th>List</th>
                  <th>Account</th>
                  <th>Compliance told</th>
                </tr>
              </thead>
              <tbody>
                {reports.items.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDate(r.matched_at)}</td>
                    <td className={ui.mono}>{r.document}</td>
                    <td>
                      <Badge tone="danger">{r.list_type}</Badge>
                    </td>
                    <td className={ui.mono}>{r.account_id.slice(0, 8)}…</td>
                    <td>
                      {r.notified_at ? formatDate(r.notified_at) : <Badge tone="warning">pending</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ResultPanel>
    </>
  );
}

/* ---------- Manager: reconciliation (HU-37 to HU-41) ---------- */

const DIFFERENCE_TEXT: Record<string, string> = {
  MISSING_IN_PARTNER: 'Missing at the partner',
  MISSING_IN_PAGOSEGURO: 'Missing at PagoSeguro',
  AMOUNT_MISMATCH: 'Amount differs',
};

function ReconciliationView({api}: {api: ApiConsole}) {
  const [status, setStatus] = useState<'PENDING' | 'RESOLVED'>('PENDING');
  const [type, setType] = useState('');
  const [differences, setDifferences] = useState<ApiResult<Page<Difference>> | null>(null);
  const [aging, setAging] = useState<ApiResult<Aging> | null>(null);
  const [runs, setRuns] = useState<ApiResult<{items: Run[]; total: number}> | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [change, setChange] = useState<ApiResult | null>(null);

  const load = useCallback(async () => {
    const query = new URLSearchParams({status, size: '100'});
    if (type) query.set('type', type);
    const [d, a, r] = await Promise.all([
      api.call<Page<Difference>>('GET', `/reconciliation/differences?${query}`),
      api.call<Aging>('GET', '/reconciliation/differences/aging'),
      api.call<{items: Run[]; total: number}>('GET', '/reconciliation/runs'),
    ]);
    setDifferences(d);
    setAging(a);
    setRuns(r);
  }, [api.call, status, type]);

  useEffect(() => {
    void load();
  }, [load]);

  const resolve = async (event: FormEvent) => {
    event.preventDefault();
    if (resolving === null) return;
    const answer = await api.call('POST', `/reconciliation/differences/${resolving}/resolution`, {
      note: note.trim(),
    });
    setChange(answer);
    if (answer.ok) {
      setResolving(null);
      setNote('');
      await load();
    }
  };

  const age = aging?.ok ? (aging.body as Aging) : null;
  const diffs = differences?.ok ? (differences.body as Page<Difference>) : null;
  const runList = runs?.ok ? (runs.body as {items: Run[]}).items : [];

  return (
    <>
      <ResultPanel result={aging} title="Pending differences by age">
        {age && (
          <div className={ui.stats}>
            <Stat label="Pending" value={age.total} />
            {age.ranges.map((range) => (
              <Stat
                key={range.range}
                label={`${range.range} days`}
                value={range.count}
                detail={Object.entries(range.by_type)
                  .filter(([, n]) => n > 0)
                  .map(([t, n]) => `${n} ${DIFFERENCE_TEXT[t]?.toLowerCase() ?? t}`)
                  .join(' · ')}
              />
            ))}
          </div>
        )}
      </ResultPanel>

      <ResultPanel
        result={differences}
        title="Differences"
        actions={
          <button type="button" className={ui.ghost} onClick={() => void load()}>
            Refresh
          </button>
        }>
        <div className={ui.toolbar}>
          <label>
            State
            <select value={status} onChange={(e) => setStatus(e.target.value as 'PENDING' | 'RESOLVED')}>
              <option value="PENDING">Pending</option>
              <option value="RESOLVED">Resolved</option>
            </select>
          </label>
          <label>
            Type
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All</option>
              {Object.entries(DIFFERENCE_TEXT).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <ActionResult result={change} success="Difference resolved." />
        {diffs && diffs.items.length === 0 && <p className={ui.empty}>No differences here.</p>}
        {diffs && diffs.items.length > 0 && (
          <div className={ui.tableWrap}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Partner</th>
                  <th>Type</th>
                  <th>Reference</th>
                  <th>PagoSeguro</th>
                  <th>Partner</th>
                  <th>Age</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {diffs.items.map((d) => (
                  <Fragment key={d.id}>
                    <tr>
                      <td>{d.run_day}</td>
                      <td>{d.partner}</td>
                      <td>
                        <Badge tone={d.type === 'AMOUNT_MISMATCH' ? 'warning' : 'danger'}>
                          {DIFFERENCE_TEXT[d.type] ?? d.type}
                        </Badge>
                      </td>
                      <td className={ui.mono}>{d.reference.slice(0, 13)}</td>
                      <td>{money(d.pagoseguro_amount, d.currency ?? undefined)}</td>
                      <td>{money(d.partner_amount, d.currency ?? undefined)}</td>
                      <td>{d.age_days} d</td>
                      <td>
                        {d.status === 'PENDING' ? (
                          <button
                            type="button"
                            className={ui.linkButton}
                            onClick={() => setResolving(resolving === d.id ? null : d.id)}>
                            {resolving === d.id ? 'Close' : 'Resolve'}
                          </button>
                        ) : (
                          <span className={ui.muted} title={d.resolution_note ?? ''}>
                            {d.resolved_by}
                          </span>
                        )}
                      </td>
                    </tr>
                    {resolving === d.id && (
                      <tr>
                        <td colSpan={8}>
                          <form className={ui.form} onSubmit={resolve}>
                            <label className={ui.wide}>
                              Note
                              <textarea
                                value={note}
                                onChange={(e) => setNote(e.target.value)}
                                required
                                placeholder="How treasury settled it"
                              />
                            </label>
                            <div className={ui.formActions}>
                              <button type="submit" className={ui.primary} disabled={!note.trim()}>
                                Mark resolved
                              </button>
                            </div>
                          </form>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ResultPanel>

      <ResultPanel result={runs} title="Nightly runs">
        {runs?.ok && runList.length === 0 && <p className={ui.empty}>No runs yet.</p>}
        {runList.length > 0 && (
          <div className={ui.tableWrap}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>State</th>
                  <th>Files</th>
                  <th>Records</th>
                  <th>Rejected</th>
                  <th>Matched</th>
                  <th>Differences</th>
                </tr>
              </thead>
              <tbody>
                {runList.map((r) => (
                  <tr key={r.run_day}>
                    <td>{r.run_day}</td>
                    <td>
                      <Badge
                        tone={r.status === 'DONE' ? 'success' : r.status === 'FAILED' ? 'danger' : 'info'}>
                        {r.status}
                      </Badge>
                      {r.error && <div className={ui.muted}>{r.error}</div>}
                    </td>
                    <td>{r.files_read ?? '—'}</td>
                    <td>{r.records_read ?? '—'}</td>
                    <td>{r.rows_rejected ?? '—'}</td>
                    <td>{r.matched ?? '—'}</td>
                    <td>{r.differences ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ResultPanel>
    </>
  );
}
