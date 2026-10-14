# SecurePay documentation site

Documentation of the PagoSeguro Anti-fraud project, built with [Docusaurus 3](https://docusaurus.io/) and published at https://securepay-riwi.github.io/SecurePay/.

## Local development

Requires Node.js 20.

```bash
npm ci
npm run start
```

Opens a local server with live reload.

## Build

```bash
npm run build
```

Generates the static site in `build/`. The build fails on broken internal links (`onBrokenLinks: 'throw'`), so run it before opening a pull request.

## Deployment

Every push to `main` that touches `doc-website/` runs `.github/workflows/doc-site.yml`, which builds the site and deploys it to GitHub Pages.

## Where things go

| Folder | Content |
| :--- | :--- |
| `docs/getting-started/` | Local setup, full flow simulation, tests |
| `docs/architecture/` | AWS design, costs, ADRs, team decisions, open questions |
| `docs/components/` | One page per piece of code |
| `docs/reference/` | Environment variables, data model, glossary |
| `docs/product-backlog/` | Epics, dependencies, sprint backlogs and reviews |

Each folder's sidebar label and position live in its `_category_.json`; each page's order in its `sidebar_position`.
