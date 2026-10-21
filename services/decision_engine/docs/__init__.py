"""Swagger (/docs) documentation of the engine, apart from the code.

One file per group of endpoints, like backend/docs/*.docs.js in NexoEDU:

- app.py: title, description and tags of the whole API.
- transactions.py: POST /transactions.
- health.py: GET /health.
- errors.py: the error bodies, which only exist to be documented.

Field descriptions stay next to each field in schemas.py, so a field and
its explanation change together. The examples match the decision-engine
page in Docusaurus; change both together.
"""
