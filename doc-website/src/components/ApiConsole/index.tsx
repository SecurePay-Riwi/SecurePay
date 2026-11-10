import {type FormEvent, type ReactNode, useCallback, useEffect, useState} from 'react';
import styles from './styles.module.css';
import {
  type ApiResult,
  type Config,
  type Role,
  type Session,
  callApi,
  cleanUrl,
  loadConfig,
  loadSession,
  regionOf,
  roleOf,
  saveConfig,
  saveSession,
  signIn,
} from './session';

export type {ApiResult, Role, Session} from './session';

const HEALTH_EVERY_MS = 15_000;

export type AwsStatus = 'idle' | 'checking' | 'on' | 'off';

export type ApiConsole = {
  config: Config;
  setConfig: (config: Config) => void;
  session: Session | null;
  setSession: (session: Session | null) => void;
  role: Role | null;
  status: AwsStatus;
  checkedAt: Date | null;
  ready: boolean;
  call: <T = unknown>(
    method: 'GET' | 'POST' | 'PUT',
    path: string,
    body?: unknown,
  ) => Promise<ApiResult<T>>;
};

/** The state every page shares: where AWS is, who signed in, and the LED. */
export function useApiConsole(): ApiConsole {
  const [config, setConfigState] = useState<Config>({apiUrl: '', clientId: ''});
  const [session, setSessionState] = useState<Session | null>(null);
  const [status, setStatus] = useState<AwsStatus>('idle');
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    setConfigState(loadConfig());
    setSessionState(loadSession());
  }, []);

  const setConfig = useCallback((value: Config) => {
    const clean = {apiUrl: cleanUrl(value.apiUrl), clientId: value.clientId.trim()};
    setConfigState(clean);
    saveConfig(clean);
  }, []);

  const setSession = useCallback((value: Session | null) => {
    setSessionState(value);
    saveSession(value);
  }, []);

  // The LED: GET /health is the only route without a token, so it answers
  // whether the HTTP API, its Lambda and the database are up.
  useEffect(() => {
    if (!config.apiUrl) {
      setStatus('idle');
      return undefined;
    }
    let cancelled = false;
    const check = async () => {
      setStatus((current) => (current === 'idle' ? 'checking' : current));
      const result = await callApi(config, null, 'GET', '/health');
      if (cancelled) return;
      setStatus(result.ok ? 'on' : 'off');
      setCheckedAt(new Date());
    };
    void check();
    const timer = setInterval(check, HEALTH_EVERY_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [config]);

  // A token lasts 60 minutes: sign out when it expires.
  useEffect(() => {
    if (!session) return undefined;
    const left = session.expiresAt - Date.now();
    const timer = setTimeout(() => setSession(null), Math.max(left, 0));
    return () => clearTimeout(timer);
  }, [session, setSession]);

  const call = useCallback(
    <T,>(method: 'GET' | 'POST' | 'PUT', path: string, body?: unknown) =>
      callApi<T>(config, session, method, path, body),
    [config, session],
  );

  return {
    config,
    setConfig,
    session,
    setSession,
    role: roleOf(session),
    status,
    checkedAt,
    ready: Boolean(config.apiUrl && session),
    call,
  };
}

const STATUS_TEXT: Record<AwsStatus, string> = {
  idle: 'No API URL yet',
  checking: 'Checking AWS…',
  on: 'AWS is on',
  off: 'AWS is off',
};

export function StatusLed({status, checkedAt}: {status: AwsStatus; checkedAt: Date | null}) {
  return (
    <span className={styles.led} data-status={status} role="status" aria-live="polite">
      <span className={styles.ledDot} aria-hidden="true" />
      <span>{STATUS_TEXT[status]}</span>
      {checkedAt && status !== 'idle' && (
        <span className={styles.ledTime}>
          · checked {checkedAt.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}
        </span>
      )}
    </span>
  );
}

const ROLE_TEXT: Record<Role, string> = {
  gerente: 'Risk manager',
  analista: 'Fraud analyst',
};

/** Where AWS is and who signs in. The URL and the client id stay in this
 * browser; the token only in this tab, until it expires (60 minutes). */
export function ConnectionPanel({api, purpose}: {api: ApiConsole; purpose: ReactNode}) {
  const [apiUrl, setApiUrl] = useState('');
  const [clientId, setClientId] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setApiUrl(api.config.apiUrl);
    setClientId(api.config.clientId);
  }, [api.config]);

  const saveConnection = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (apiUrl && !regionOf(apiUrl)) {
      setError('That is not an API Gateway URL (https://<id>.execute-api.<region>.amazonaws.com).');
      return;
    }
    api.setConfig({apiUrl, clientId});
  };

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      api.setSession(await signIn(api.config, email, password));
      setPassword('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const changed = apiUrl !== api.config.apiUrl || clientId !== api.config.clientId;

  return (
    <section className={styles.connection} aria-label="Connection to AWS">
      <div className={styles.connectionHead}>
        <h2>Connection</h2>
        <StatusLed status={api.status} checkedAt={api.checkedAt} />
      </div>
      <p className={styles.help}>{purpose}</p>

      <form className={styles.connectionGrid} onSubmit={saveConnection}>
        <label>
          API URL <code>terraform output -raw api_url</code>
          <input
            value={apiUrl}
            onChange={(event) => setApiUrl(event.target.value)}
            placeholder="https://abc123.execute-api.us-east-2.amazonaws.com"
            spellCheck={false}
          />
        </label>
        <label>
          App client <code>terraform output -raw user_pool_client_id</code>
          <input
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            placeholder="1a2b3c4d5e6f7g8h9i0j"
            spellCheck={false}
          />
        </label>
        <button type="submit" className={styles.primary} disabled={!changed}>
          Save
        </button>
      </form>

      {api.session ? (
        <div className={styles.user}>
          <span className={styles.avatar} aria-hidden="true">
            {api.session.email.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{api.session.email}</strong>
            <span className={styles.roleTag} data-role={api.role ?? 'none'}>
              {api.role ? ROLE_TEXT[api.role] : 'No group'}
            </span>
          </div>
          <button type="button" className={styles.ghost} onClick={() => api.setSession(null)}>
            Sign out
          </button>
        </div>
      ) : (
        <form className={styles.loginGrid} onSubmit={login}>
          <label>
            E-mail
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="gerente@example.com"
              required
            />
          </label>
          <label>
            Password <code>terraform output -json api_user_passwords</code>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          <button
            type="submit"
            className={styles.primary}
            disabled={busy || !api.config.apiUrl || !api.config.clientId}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      )}
      {error && <p className={styles.error}>{error}</p>}
      {api.status === 'off' && (
        <p className={styles.warning}>
          The API does not answer. If dev is destroyed this is expected: bring it up with{' '}
          <code>terraform apply</code> and paste the new URL (it changes with every apply).
        </p>
      )}
    </section>
  );
}

/** A result shown as a page, with its raw request and response one tab away. */
export function ResultPanel({
  result,
  title,
  children,
  actions,
}: {
  result: ApiResult | null;
  title: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const [tab, setTab] = useState<'view' | 'json'>('view');
  return (
    <section className={styles.panel}>
      <header className={styles.panelHead}>
        <h2>{title}</h2>
        <div className={styles.panelTools}>
          {actions}
          <div className={styles.switch} role="tablist" aria-label="Show as">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'view'}
              className={tab === 'view' ? styles.switchOn : undefined}
              onClick={() => setTab('view')}>
              View
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'json'}
              className={tab === 'json' ? styles.switchOn : undefined}
              onClick={() => setTab('json')}
              disabled={!result}>
              JSON
            </button>
          </div>
        </div>
      </header>
      {result && !result.ok && <p className={styles.error}>{result.error}</p>}
      {tab === 'view' || !result ? children : <JsonView result={result} />}
    </section>
  );
}

export function JsonView({result}: {result: ApiResult}) {
  return (
    <div className={styles.json}>
      <p className={styles.requestLine}>
        <code>
          {result.method} {result.path}
        </code>
        <span>
          {result.status === null ? 'no answer' : `HTTP ${result.status}`} · {result.elapsedMs} ms
        </span>
      </p>
      {result.requestBody !== undefined && (
        <>
          <h3>Request</h3>
          <pre>{JSON.stringify(result.requestBody, null, 2)}</pre>
        </>
      )}
      <h3>Response</h3>
      <pre>
        {typeof result.body === 'string' ? result.body : JSON.stringify(result.body, null, 2)}
      </pre>
    </div>
  );
}

/** The small toast after a change: what happened, and its JSON on demand. */
export function ActionResult({result, success}: {result: ApiResult | null; success: ReactNode}) {
  const [open, setOpen] = useState(false);
  if (!result) return null;
  return (
    <div className={styles.toast} data-ok={result.ok}>
      <span>{result.ok ? success : result.error}</span>
      <button type="button" className={styles.linkButton} onClick={() => setOpen(!open)}>
        {open ? 'Hide JSON' : 'JSON'}
      </button>
      {open && <JsonView result={result} />}
    </div>
  );
}

export function Gate({api, children}: {api: ApiConsole; children: ReactNode}) {
  if (!api.config.apiUrl) {
    return <p className={styles.empty}>Paste the API URL and the app client above to start.</p>;
  }
  if (!api.session) {
    return <p className={styles.empty}>Sign in with a Cognito user to load the data.</p>;
  }
  return <>{children}</>;
}

export function Badge({tone, children}: {tone: string; children: ReactNode}) {
  return (
    <span className={styles.badge} data-tone={tone}>
      {children}
    </span>
  );
}

export function decisionTone(decision: string | null | undefined): string {
  if (decision === 'REJECT') return 'danger';
  if (decision === 'HOLD') return 'warning';
  if (decision === 'APPROVE') return 'success';
  return 'neutral';
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});
}

export function money(amount: string | null | undefined, currency?: string): string {
  if (amount === null || amount === undefined) return '—';
  const number = Number(amount);
  if (Number.isNaN(number)) return amount;
  const text = number.toLocaleString('en-US', {
    minimumFractionDigits: currency === 'JPY' ? 0 : 2,
    maximumFractionDigits: currency === 'JPY' ? 0 : 2,
  });
  return currency ? `${text} ${currency}` : text;
}

export function Stat({
  label,
  value,
  detail,
  small,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  small?: boolean;
}) {
  return (
    <div className={styles.stat}>
      <span>{label}</span>
      <strong style={small ? {fontSize: '1rem'} : undefined}>{value}</strong>
      {detail && <div className={styles.muted}>{detail}</div>}
    </div>
  );
}

export {styles as consoleStyles};
