// The stations of the transaction map: what each AWS piece is, where it
// sits in each drawing and what it does. Times and numbers come from
// infra/terraform/modules (schedules, batching) and AGENTS.md.

export type Side = 'below' | 'above' | 'right' | 'aboveLeft' | 'aboveRight';
export type Place = {x: number; y: number; side: Side};

export type Station = {
  name: string;
  service: string;
  about: string;
  wide: Place;
  narrow?: Place; // the narrow map draws only the transaction's stations
  big?: boolean;
  extra?: boolean; // shown only with the whole system
};

export const STATIONS = {
  core: {
    name: 'Wallet core',
    service: 'simulated',
    about:
      "PagoSeguro's payments system, simulated by securepay-generator. It sends each transaction to the engine and waits for APPROVE, HOLD or REJECT.",
    wide: {x: 40, y: 120, side: 'below'},
    narrow: {x: 160, y: 30, side: 'right'},
  },
  alb: {
    name: 'Load balancer',
    service: 'ALB',
    about:
      "Application Load Balancer on HTTPS. It spreads the requests over the engine's tasks and stops sending to one that fails its health check.",
    wide: {x: 150, y: 120, side: 'below'},
    narrow: {x: 160, y: 105, side: 'right'},
  },
  engine: {
    name: 'Engine',
    service: 'ECS Fargate',
    about:
      'The decision engine (FastAPI). It reads the accounts, the merchant and the restricted list from the cache, writes the account history, runs every rule of the catalog and answers in under 200 ms. More tasks start when CPU or requests per task go up.',
    wide: {x: 265, y: 120, side: 'below'},
    narrow: {x: 160, y: 185, side: 'right'},
    big: true,
  },
  cache: {
    name: 'Cache',
    service: 'ElastiCache Valkey',
    about:
      'Everything the engine needs in microseconds: accounts, merchants and the restricted list, the history windows of each account, the rules catalog and the decisions already taken (a retry gets the same answer).',
    wide: {x: 265, y: 40, side: 'above'},
    narrow: {x: 55, y: 185, side: 'above'},
  },
  topic: {
    name: 'Decisions topic',
    service: 'SNS',
    about:
      'The engine publishes each decision here in the background, after answering, so the core never waits for it. The topic copies it to three queues.',
    wide: {x: 385, y: 120, side: 'aboveLeft'},
    narrow: {x: 160, y: 275, side: 'right'},
  },
  qCases: {
    name: 'Cases queue',
    service: 'SQS',
    about:
      'Holds the decisions until the cases consumer reads them. After 5 failed attempts a message moves to its dead-letter queue.',
    wide: {x: 500, y: 40, side: 'above'},
    narrow: {x: 55, y: 370, side: 'aboveLeft'},
  },
  qHistory: {
    name: 'History queue',
    service: 'SQS',
    about:
      'Holds the decisions until the history consumer reads them. After 5 failed attempts a message moves to its dead-letter queue.',
    wide: {x: 500, y: 120, side: 'below'},
    narrow: {x: 160, y: 370, side: 'aboveRight'},
  },
  qAnalytics: {
    name: 'Analytics queue',
    service: 'SQS',
    about:
      'Holds the decisions until the analytics consumer reads them, in batches of up to 1,000 or every 60 seconds.',
    wide: {x: 500, y: 200, side: 'below'},
    narrow: {x: 250, y: 370, side: 'aboveRight'},
  },
  lCases: {
    name: 'Cases consumer',
    service: 'Lambda',
    about:
      'Opens a case when the decision says so (mule, splitting, restricted list) and, for the restricted list, one compliance report per listed owner. Other decisions it reads and leaves.',
    wide: {x: 615, y: 40, side: 'above'},
    narrow: {x: 55, y: 455, side: 'right'},
  },
  lHistory: {
    name: 'History consumer',
    service: 'Lambda',
    about:
      'Writes one row per account of every decision, whatever it was: the 30-day history an analyst reads with a case.',
    wide: {x: 615, y: 120, side: 'below'},
    narrow: {x: 160, y: 455, side: 'right'},
  },
  lAnalytics: {
    name: 'Analytics consumer',
    service: 'Lambda',
    about: "Writes each batch of decisions as one file in the data lake's raw layer, by day.",
    wide: {x: 615, y: 200, side: 'below'},
    narrow: {x: 250, y: 455, side: 'right'},
  },
  cases: {
    name: 'Case opened',
    service: 'RDS PostgreSQL',
    about:
      'The case, with a 4-hour limit (RN-09), every change of it in an append-only log, and the compliance reports.',
    wide: {x: 740, y: 40, side: 'above'},
    narrow: {x: 55, y: 545, side: 'below'},
  },
  history: {
    name: 'History DB',
    service: 'RDS PostgreSQL',
    about: 'The account history of the last 30 days; older rows are purged every 5 minutes.',
    wide: {x: 740, y: 120, side: 'below'},
    narrow: {x: 160, y: 545, side: 'below'},
  },
  lake: {
    name: 'Data lake',
    service: 'S3',
    about:
      'Raw decisions by day, then the curated layer and the dimensional model the nightly job builds.',
    wide: {x: 740, y: 200, side: 'below'},
    narrow: {x: 250, y: 545, side: 'below'},
  },

  // The rest of the system: they do not touch this transaction.
  rulesApi: {
    name: 'Rules API',
    service: 'API Gateway + Lambda',
    about:
      'The risk team creates, versions and switches rules on or off here. Each change is published to the cache and the engine uses it within a second, without a redeploy (RF-03).',
    wide: {x: 150, y: 40, side: 'above'},
    extra: true,
  },
  listLoader: {
    name: 'List loader',
    service: 'Lambda, 01:00',
    about:
      'Every night loads the accounts, merchants and restricted list from the database into the cache. The engine never reads the database itself.',
    wide: {x: 385, y: 40, side: 'above'},
    extra: true,
  },
  rates: {
    name: 'Exchange rates',
    service: 'DynamoDB, 11:00',
    about:
      "A Lambda saves the day's Frankfurter rates. The engine keeps the whole table in memory and refreshes it in the background, so a decision never waits for it (RN-11).",
    wide: {x: 60, y: 290, side: 'below'},
    extra: true,
  },
  dlq: {
    name: 'Dead-letter queues',
    service: 'SQS',
    about:
      'A message that failed 5 times waits here instead of being lost, and an alarm e-mails operations.',
    wide: {x: 500, y: 290, side: 'below'},
    extra: true,
  },
  casesApi: {
    name: 'Cases API',
    service: 'API Gateway + Cognito',
    about:
      "The analysts' inbox: cases by risk score and time left, the account's history and related accounts, assignment and resolution. Sign-in with Cognito.",
    wide: {x: 615, y: -50, side: 'above'},
    extra: true,
  },
  alerts: {
    name: 'Alerts',
    service: 'Lambda, every 5 min',
    about:
      'Escalates the cases still open after 4 hours and e-mails the supervisor, and sends compliance its restricted-list reports (RN-06, RN-09).',
    wide: {x: 800, y: -50, side: 'above'},
    extra: true,
  },
  evidence: {
    name: 'Evidence',
    service: 'S3 Object Lock',
    about:
      'When a case is resolved, its transaction, decision, analyst and resolution are written once with Object Lock in compliance mode: nobody can change or delete them for 10 years (RN-12).',
    wide: {x: 850, y: 40, side: 'above'},
    extra: true,
  },
  nightly: {
    name: 'Nightly jobs',
    service: 'Step Functions + Glue',
    about:
      "At 02:00 reads the partners' statements, reconciles them with the approved transactions in Spark on Glue (RN-10), stores the differences and builds the analytics model.",
    wide: {x: 615, y: 290, side: 'below'},
    extra: true,
  },
  powerbi: {
    name: 'Power BI',
    service: 'Athena views',
    about:
      "Six Athena views over the data lake answer the dashboard's questions: volumes, rule precision, fraud caught and missed, cases, reconciliation and risk.",
    wide: {x: 850, y: 200, side: 'below'},
    extra: true,
  },
} satisfies Record<string, Station>;

export type StationId = keyof typeof STATIONS;

export const LINES: [StationId, StationId][] = [
  ['core', 'alb'],
  ['alb', 'engine'],
  ['engine', 'cache'],
  ['engine', 'topic'],
  ['topic', 'qCases'],
  ['topic', 'qHistory'],
  ['topic', 'qAnalytics'],
  ['qCases', 'lCases'],
  ['qHistory', 'lHistory'],
  ['qAnalytics', 'lAnalytics'],
  ['lCases', 'cases'],
  ['lHistory', 'history'],
  ['lAnalytics', 'lake'],
];

// Dashed: the rest of the system, shown with its stations. The number is
// a gap: the line stops that many units short of its end, so it does not
// cross that station's label.
export const EXTRA_LINES: [StationId, StationId, number?][] = [
  ['rulesApi', 'cache'],
  ['listLoader', 'cache'],
  ['rates', 'engine', 70],
  ['dlq', 'qAnalytics', 46],
  ['casesApi', 'cases', 62],
  ['alerts', 'cases', 50],
  ['cases', 'evidence'],
  ['nightly', 'lake'],
  ['lake', 'powerbi'],
];

export const ROUTE_IN: StationId[] = ['core', 'alb', 'engine'];
export const ROUTE_CACHE: StationId[] = ['engine', 'cache', 'engine'];
export const ROUTE_BACK: StationId[] = ['engine', 'alb', 'core'];
export const ROUTES_OUT: {key: string; route: StationId[]}[] = [
  {key: 'cases', route: ['engine', 'topic', 'qCases', 'lCases', 'cases']},
  {key: 'history', route: ['engine', 'topic', 'qHistory', 'lHistory', 'history']},
  {key: 'analytics', route: ['engine', 'topic', 'qAnalytics', 'lAnalytics', 'lake']},
];
export const STORES: StationId[] = ['cases', 'history', 'lake'];
