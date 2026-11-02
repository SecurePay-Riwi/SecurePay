"""Reconciliation differences for treasury (HU-38 to HU-41, RN-10).

The reconciliation (services/reconciliation/) writes the differences;
these routes list them, show their age and resolve them. Tables and
states: shared/reconciliation.py.
"""

from fastapi import APIRouter

router = APIRouter(tags=["Reconciliation"])
