// The connection of the Rules API and Cases API pages: the HTTP API of AWS
// (terraform output api_url), the Cognito app client (user_pool_client_id)
// and the signed-in user's ID token. Nothing here is a secret: the URL and
// the client id are public, the token lives only in this browser tab.

export type Role = 'gerente' | 'analista';

export type Config = {
  apiUrl: string;
  clientId: string;
};

export type Session = {
  idToken: string;
  email: string;
  groups: string[];
  expiresAt: number; // epoch ms
};

export type ApiResult<T = unknown> = {
  method: string;
  path: string;
  requestBody?: unknown;
  status: number | null;
  ok: boolean;
  elapsedMs: number;
  body: T | string | null;
  error?: string;
};

const CONFIG_KEY = 'securepay.api-console.config';
const SESSION_KEY = 'securepay.api-console.session';
const TIMEOUT_MS = 30_000;

function storage(kind: 'local' | 'session'): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function loadConfig(): Config {
  try {
    const raw = storage('local')?.getItem(CONFIG_KEY);
    if (raw) {
      const value = JSON.parse(raw) as Partial<Config>;
      return {apiUrl: value.apiUrl ?? '', clientId: value.clientId ?? ''};
    }
  } catch {
    // A broken value is the same as none.
  }
  return {apiUrl: '', clientId: ''};
}

export function saveConfig(config: Config): void {
  try {
    storage('local')?.setItem(CONFIG_KEY, JSON.stringify(config));
  } catch {
    // Private windows may refuse storage: the page still works this visit.
  }
}

export function loadSession(): Session | null {
  try {
    const raw = storage('session')?.getItem(SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Session;
    return value.expiresAt > Date.now() ? value : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session | null): void {
  try {
    const store = storage('session');
    if (!store) return;
    if (session) store.setItem(SESSION_KEY, JSON.stringify(session));
    else store.removeItem(SESSION_KEY);
  } catch {
    // Same as above.
  }
}

/** "https://abc.execute-api.us-east-2.amazonaws.com/" -> its base, no slash. */
export function cleanUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

/** The region of the HTTP API, which is also the user pool's (one region). */
export function regionOf(apiUrl: string): string | null {
  const match = /\.execute-api\.([a-z0-9-]+)\.amazonaws\.com/.exec(apiUrl);
  return match ? match[1] : null;
}

function decodeClaims(token: string): Record<string, unknown> {
  const part = token.split('.')[1] ?? '';
  const base64 = part.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
  const bytes = Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
}

/** Signs in with the user pool's USER_PASSWORD_AUTH flow (the one the app
 * client allows) and keeps the ID token: it carries the e-mail that API
 * Gateway writes into X-User, and the groups. */
export async function signIn(
  config: Config,
  email: string,
  password: string,
): Promise<Session> {
  const region = regionOf(config.apiUrl);
  if (!region) throw new Error('The API URL is not an execute-api URL of AWS.');
  if (!config.clientId.trim()) throw new Error('Paste the user_pool_client_id first.');
  const response = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
    },
    body: JSON.stringify({
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: config.clientId.trim(),
      AuthParameters: {USERNAME: email.trim(), PASSWORD: password},
    }),
  });
  const body = (await response.json().catch(() => ({}))) as {
    AuthenticationResult?: {IdToken: string; ExpiresIn: number};
    ChallengeName?: string;
    message?: string;
  };
  if (!response.ok) {
    throw new Error(body.message ?? `Cognito answered HTTP ${response.status}.`);
  }
  if (body.ChallengeName) {
    throw new Error(
      `Cognito asks for ${body.ChallengeName}: set a permanent password for this user ` +
        '(aws cognito-idp admin-set-user-password --permanent) and try again.',
    );
  }
  const token = body.AuthenticationResult?.IdToken;
  if (!token) throw new Error('Cognito did not return an ID token.');
  const claims = decodeClaims(token);
  const groups = claims['cognito:groups'];
  return {
    idToken: token,
    email: String(claims.email ?? email),
    groups: Array.isArray(groups) ? groups.map(String) : [],
    expiresAt: Number(claims.exp ?? 0) * 1000 || Date.now() + body.AuthenticationResult!.ExpiresIn * 1000,
  };
}

export function roleOf(session: Session | null): Role | null {
  if (!session) return null;
  if (session.groups.includes('gerente')) return 'gerente';
  if (session.groups.includes('analista')) return 'analista';
  return null;
}

/** One call to the HTTP API with the session's token. Never throws: a
 * network, CORS or TLS error comes back as a failed result. */
export async function callApi<T = unknown>(
  config: Config,
  session: Session | null,
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  const started = performance.now();
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (session) headers.Authorization = `Bearer ${session.idToken}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(`${cleanUrl(config.apiUrl)}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    let parsed: unknown = text;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      // Not JSON (the suspicious report as CSV): keep the text.
    }
    return {
      method,
      path,
      requestBody: body,
      status: response.status,
      ok: response.ok,
      elapsedMs: Math.round(performance.now() - started),
      body: parsed as T,
      error: response.ok ? undefined : errorText(response.status, parsed),
    };
  } catch (error) {
    return {
      method,
      path,
      requestBody: body,
      status: null,
      ok: false,
      elapsedMs: Math.round(performance.now() - started),
      body: null,
      error:
        error instanceof DOMException && error.name === 'AbortError'
          ? `No answer in ${TIMEOUT_MS / 1000} s.`
          : 'Network error: AWS is off, the URL is wrong, or CORS refused the page.',
    };
  } finally {
    clearTimeout(timer);
  }
}

function errorText(status: number, body: unknown): string {
  if (status === 401) return 'Sign in again: the token is missing or expired.';
  if (status === 403) {
    const detail = typeof body === 'object' && body && 'detail' in body ? body.detail : null;
    return typeof detail === 'string' ? detail : 'Your role may not do this.';
  }
  if (typeof body === 'object' && body && 'detail' in body) {
    const detail = (body as {detail: unknown}).detail;
    if (typeof detail === 'string') return detail;
    if (typeof detail === 'object' && detail && 'detail' in detail) {
      return String((detail as {detail: unknown}).detail);
    }
  }
  return `HTTP ${status}`;
}
