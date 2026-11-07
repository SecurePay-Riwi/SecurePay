import {useEffect, useState} from 'react';
import useBaseUrl from '@docusaurus/useBaseUrl';

// Types of static/demo/scenarios.json (format_version 1), written by
// services/analytics/demo.py. The page only reads it: every decision,
// amount and rate comes from the engine's own code.

export type DecisionValue = 'APPROVE' | 'HOLD' | 'REJECT';

export type CatalogRule = {
  code: string;
  title: string;
  rn: string | null;
  action: DecisionValue;
  opens_case: boolean;
  score: number;
  enabled: boolean;
  description: string;
  params: Record<string, string | number>;
};

export type Decision = {
  transaction_id: string;
  decision: DecisionValue;
  decision_reason: string;
  rules_version: string;
  rules_triggered: string[];
  rule_versions: Record<string, number>;
  opens_case: boolean;
  amount_usd: string;
  usd_rate: string;
  rate_date: string;
  risk_score: number;
  by_default: boolean;
};

export type TransactionRequest = {
  id: string;
  type: 'P2P' | 'QR' | 'RECARGA' | 'RETIRO';
  channel: string;
  amount: string;
  currency: string;
  transaction_date: string;
  device_id: string;
  source_account_id?: string;
  destination_account_id?: string;
  merchant_id?: string;
};

export type SecurityEventRequest = {
  id: string;
  type: 'DEVICE_CHANGE' | 'PASSWORD_CHANGE';
  account_id: string;
  device_id: string;
  event_date: string;
};

export type Step =
  | {kind: 'transaction'; label: string; request: TransactionRequest; decision: Decision}
  | {kind: 'security_event'; label: string; request: SecurityEventRequest};

export type After = {
  queues: string[];
  opens_case: boolean;
  case_due_minutes: number | null;
  compliance_report: boolean;
  evidence: string | null;
};

export type Scenario = {
  id: string;
  title: string;
  rn: string;
  story: string;
  steps: Step[];
  after: After;
};

export type ThresholdValue = {
  value: number;
  decisions: Record<string, DecisionValue>;
  changed: number;
};

export type ThresholdVariant = {
  rule: string;
  param: string;
  default: number;
  values: ThresholdValue[];
};

export type DemoData = {
  format_version: number;
  generated_from: string;
  catalog: {version: string; rules: CatalogRule[]};
  scenarios: Scenario[];
  threshold_variants: ThresholdVariant[];
};

export const FORMAT_VERSION = 1;

/** The transaction the scenario is about: its last one. */
export function protagonist(scenario: Scenario) {
  const transactions = scenario.steps.filter(
    (s): s is Extract<Step, {kind: 'transaction'}> => s.kind === 'transaction',
  );
  return transactions[transactions.length - 1];
}

export function stepTime(step: Step): string {
  const iso =
    step.kind === 'transaction' ? step.request.transaction_date : step.request.event_date;
  return iso.slice(11, 16); // HH:MM, UTC
}

export function formatAmount(amount: string, currency: string): string {
  const [whole, cents] = amount.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${currency} ${cents ? `${grouped}.${cents}` : grouped}`;
}

type State = {data?: DemoData; error?: string};

export function useDemoData(): State {
  const url = useBaseUrl('/demo/scenarios.json');
  const [state, setState] = useState<State>({});
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<DemoData>;
      })
      .then((data) => {
        if (cancelled) return;
        if (data.format_version !== FORMAT_VERSION) {
          throw new Error(`format_version ${data.format_version} is not ${FORMAT_VERSION}`);
        }
        setState({data});
      })
      .catch((error: Error) => {
        if (!cancelled) setState({error: error.message});
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  return state;
}

/** True when the visitor asked the system for less motion. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(query.matches);
    const onChange = () => setReduced(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return reduced;
}
