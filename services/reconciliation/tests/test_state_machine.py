"""The nightly state machine, validated without AWS (HU-66, MAG-292).

Step Functions replaces Airflow (ADR-06), so the "DAG validation" of the
data CI is this: modules/reconciliation renders the machine from
state_machine.json.tftpl, and this test renders the same template with
placeholder values and checks what Step Functions would reject or what
would break at night: unknown states, a state with neither Next nor End,
states nobody reaches, a Catch to nowhere, a Task without retries, and a
step that reads a field ($.ingest.day, $.store.matched) that no earlier
step writes.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "infra" / "terraform" / "modules" / "reconciliation"
TEMPLATE = MODULE / "state_machine.json.tftpl"

TERMINAL = {"Succeed", "Fail"}
TYPES = {"Task", "Pass", "Choice", "Wait", "Succeed", "Fail", "Parallel", "Map"}
# The service integrations the machine may use (and the roles allow).
RESOURCES = {
    "arn:aws:states:::lambda:invoke",
    "arn:aws:states:::glue:startJobRun.sync",
    "arn:aws:states:::sns:publish",
    "arn:aws:states:::athena:startQueryExecution.sync",
}
PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
FIELD = re.compile(r"\$\.(\w+)\.(\w+)")


def template_variables() -> set[str]:
    return set(PLACEHOLDER.findall(TEMPLATE.read_text(encoding="utf-8")))


def render(values: dict | None = None) -> dict:
    """The template with every ${name} replaced, as templatefile() does."""
    values = values or {}

    def value(found):
        name = found.group(1)
        return str(values.get(name, 300 if name.endswith("_seconds") else name))

    return json.loads(PLACEHOLDER.sub(value, TEMPLATE.read_text(encoding="utf-8")))


def targets(state: dict) -> list[str]:
    """Every state this one may go to."""
    found = [state["Next"]] if "Next" in state else []
    found += [c["Next"] for c in state.get("Catch", [])]
    found += [c["Next"] for c in state.get("Choices", [])]
    if "Default" in state:
        found.append(state["Default"])
    return found


def problems(machine: dict) -> list[str]:
    """What is wrong with a definition; empty when it is valid."""
    states = machine.get("States", {})
    found = []
    if machine.get("StartAt") not in states:
        found.append(f"StartAt {machine.get('StartAt')!r} is not a state")
    for name, state in states.items():
        kind = state.get("Type")
        if kind not in TYPES:
            found.append(f"{name}: unknown Type {kind!r}")
        if kind not in TERMINAL and kind != "Choice":
            if ("Next" in state) == bool(state.get("End")):
                found.append(f"{name}: needs exactly one of Next and End")
        for target in targets(state):
            if target not in states:
                found.append(f"{name}: goes to {target!r}, which is not a state")
        if kind == "Task":
            if state.get("Resource") not in RESOURCES:
                found.append(f"{name}: unexpected Resource {state.get('Resource')}")
            if not state.get("Retry"):
                found.append(f"{name}: a Task without Retry")
            if not state.get("Catch"):
                found.append(f"{name}: a Task without Catch")
        for key, value in _paths(state.get("Parameters", {})):
            if not (value.startswith("$") or value.startswith("States.")):
                found.append(f"{name}: {key} must be a path or an intrinsic")

    reached, pending = set(), [machine.get("StartAt")]
    while pending:
        name = pending.pop()
        if name in reached or name not in states:
            continue
        reached.add(name)
        pending.extend(targets(states[name]))
    found += [f"{name}: no state goes to it" for name in states if name not in reached]
    return found + _unknown_fields(machine)


def _paths(parameters, prefix=""):
    """(key, value) of every "<key>.$" in Parameters, at any depth."""
    for key, value in parameters.items():
        if isinstance(value, dict):
            yield from _paths(value, f"{prefix}{key}.")
        elif key.endswith(".$"):
            yield f"{prefix}{key}", value


def _unknown_fields(machine: dict) -> list[str]:
    """A step that reads $.<result>.<field> where <result> is the
    ResultPath of a step whose ResultSelector does not have <field>."""
    written = {}
    for state in machine["States"].values():
        path = state.get("ResultPath")
        if isinstance(path, str) and "ResultSelector" in state:
            written[path.removeprefix("$.")] = {
                k.removesuffix(".$") for k in state["ResultSelector"]
            }
    found = []
    for name, state in machine["States"].items():
        text = json.dumps({k: v for k, v in state.items() if k != "ResultSelector"})
        for result, field in FIELD.findall(text):
            if result in written and field not in written[result]:
                found.append(f"{name}: reads $.{result}.{field}, never written")
    return found


# --- the template -------------------------------------------------------------


def test_the_template_renders_to_valid_json():
    machine = render()

    assert machine["StartAt"] == "ReadStatements"
    assert problems(machine) == []


def test_terraform_passes_every_variable_of_the_template():
    source = (MODULE / "main.tf").read_text(encoding="utf-8")
    call = source[source.index("templatefile(") :]
    call = call[: call.index("})")]
    passed = set(re.findall(r"^\s*(\w+)\s*=", call, re.MULTILINE))

    assert passed == template_variables()


def test_the_reconciliation_path_ends_by_telling_treasury():
    machine = render()
    order, name = [], machine["StartAt"]
    while name:
        order.append(name)
        name = machine["States"][name].get("Next")

    assert order[:3] == ["ReadStatements", "MatchWithSpark", "SaveDifferences"]
    assert order[-1] == "NotifyTreasury"
    assert machine["States"]["NotifyTreasury"]["End"] is True


def test_every_error_ends_in_reconciliation_failed():
    machine = render()
    for name, state in machine["States"].items():
        for catch in state.get("Catch", []):
            if catch["ErrorEquals"] == ["States.ALL"] and name in (
                "ReadStatements",
                "MatchWithSpark",
                "SaveDifferences",
                "NotifyTreasury",
            ):
                assert catch["Next"] == "ReconciliationFailed", name


# --- and the checks catch what they should ------------------------------------


def _broken(change) -> list[str]:
    machine = render()
    change(machine["States"])
    return problems(machine)


@pytest.mark.parametrize(
    "change, expected",
    [
        (
            lambda s: s["MatchWithSpark"].update(Next="Nowhere"),
            "MatchWithSpark: goes to 'Nowhere', which is not a state",
        ),
        (
            lambda s: s["NotifyTreasury"].pop("End"),
            "NotifyTreasury: needs exactly one of Next and End",
        ),
        (
            lambda s: s["SaveDifferences"].update(Next="NotifyTreasury", End=True),
            "SaveDifferences: needs exactly one of Next and End",
        ),
        (
            lambda s: s.update(Orphan={"Type": "Succeed"}),
            "Orphan: no state goes to it",
        ),
        (
            lambda s: s["ReadStatements"].pop("Retry"),
            "ReadStatements: a Task without Retry",
        ),
        (
            lambda s: s["SaveDifferences"]["Parameters"]["Payload"].update(
                {"day.$": "$.ingest.dia"}
            ),
            "SaveDifferences: reads $.ingest.dia, never written",
        ),
        (
            lambda s: s["ReadStatements"]["Parameters"].update(
                {"FunctionName.$": "arn"}
            ),
            "ReadStatements: FunctionName.$ must be a path or an intrinsic",
        ),
    ],
)
def test_a_broken_definition_is_caught(change, expected):
    assert expected in _broken(change)
