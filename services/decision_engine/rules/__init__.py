"""The rules the engine knows how to evaluate, by type.

The catalog (shared/rule_catalog.py) says which rules run, in which
order and with which parameters; this registry maps each type to its
code. A new rule type adds one line here.
"""

from services.decision_engine.rules import (
    account_takeover,
    mule,
    restricted_list,
    shared_device,
    velocity,
)

REGISTRY = {
    m.TYPE: m
    for m in (restricted_list, velocity, mule, shared_device, account_takeover)
}
