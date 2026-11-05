"""infra/terraform/scripts/dev_up.py, what `terraform apply` of dev runs
on the applying computer: image tags, the push and the seed task."""

import importlib.util
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "infra" / "terraform" / "scripts" / "dev_up.py"
spec = importlib.util.spec_from_file_location("dev_up", SCRIPT)
dev_up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev_up)


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(folder), *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def _clone(folder: Path) -> str:
    folder.mkdir()
    _git(folder, "init", "-q")
    (folder / "Dockerfile").write_text("FROM scratch\n")
    _git(folder, "add", ".")
    _git(
        folder,
        "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x",
    )  # fmt: skip
    return _git(folder, "rev-parse", "--short", "HEAD")


def test_a_clean_clone_is_tagged_with_its_short_commit(tmp_path):
    commit = _clone(tmp_path / "SecurePay")
    assert dev_up.image_tag(tmp_path / "SecurePay") == commit


def test_uncommitted_changes_get_a_tag_of_their_own(tmp_path):
    folder = tmp_path / "SecurePay"
    commit = _clone(folder)
    (folder / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    first = dev_up.image_tag(folder)
    assert first.startswith(f"{commit}-dirty-")

    (folder / "Dockerfile").write_text("FROM scratch\nRUN false\n")
    assert dev_up.image_tag(folder) not in (first, commit)


def test_a_missing_clone_is_not_built(tmp_path):
    assert dev_up.image_tag(tmp_path / "nothing") == ""
    (tmp_path / "plain").mkdir()
    assert dev_up.image_tag(tmp_path / "plain") == ""


def test_tags_finds_the_clones_beside_securepay(tmp_path):
    engine = _clone(tmp_path / "my-securepay")
    seed = _clone(tmp_path / "securepay-seed")

    assert dev_up.tags({"securepay": str(tmp_path / "my-securepay")}) == {
        "engine": engine,
        "admin": seed,
        "apis": "",
    }


def test_the_tags_command_answers_terraform_in_json(tmp_path, monkeypatch, capsys):
    engine = _clone(tmp_path / "SecurePay")
    query = json.dumps({"securepay": str(tmp_path / "SecurePay")})
    monkeypatch.setattr("sys.stdin", io.StringIO(query))

    dev_up.main(["tags"])

    assert json.loads(capsys.readouterr().out) == {
        "engine": engine,
        "admin": "",
        "apis": "",
    }


class Commands:
    """subprocess.run that records each command and answers from a table."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        for start, answer in self.answers.items():
            if " ".join(args).startswith(start):
                return SimpleNamespace(
                    **{"returncode": 0, "stdout": "", "stderr": "", **answer}
                )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def ran(self, start: str) -> list:
        return [c for c in self.calls if " ".join(c[0]).startswith(start)]


REPO = "123.dkr.ecr.us-east-2.amazonaws.com/securepay-dev-engine"


def test_a_tag_already_in_ecr_is_not_built_again(monkeypatch):
    commands = Commands({})
    monkeypatch.setattr(subprocess, "run", commands)

    dev_up.push(REPO, "abc1234", ".", "us-east-2")

    assert commands.ran("aws ecr describe-images")
    assert not commands.ran("docker")


def test_a_new_tag_is_built_without_provenance_and_pushed(monkeypatch):
    commands = Commands(
        {
            "aws ecr describe-images": {"returncode": 254},
            "aws ecr get-login-password": {"stdout": "secret\n"},
        }
    )
    monkeypatch.setattr(subprocess, "run", commands)

    dev_up.push(REPO, "abc1234", "/src", "us-east-2")

    login = commands.ran("docker login")[0]
    assert "secret" not in login[0] and login[1]["input"] == "secret"
    assert login[0][-1] == "123.dkr.ecr.us-east-2.amazonaws.com"
    build = commands.ran("docker build")[0][0]
    assert "--provenance=false" in build and build[-1] == "/src"
    assert commands.ran(f"docker push {REPO}:abc1234")


def _task(status: str, code: int | None = None) -> str:
    return json.dumps(
        {
            "tasks": [
                {
                    "lastStatus": status,
                    "containers": [{"exitCode": code}],
                    "stoppedReason": "Essential container in task exited",
                }
            ]
        }
    )


def _run_seed(monkeypatch, *states: str):
    answers = iter(states)
    commands = Commands({"aws ecs --region us-east-2 run-task": {"stdout": "arn:task"}})

    def run(args, **kwargs):
        if "describe-tasks" in args:
            commands.calls.append((list(args), kwargs))
            return SimpleNamespace(returncode=0, stdout=next(answers), stderr="")
        return commands(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(dev_up.time, "sleep", lambda seconds: None)
    dev_up.run_task(
        "securepay-dev", "securepay-dev-admin:3", "subnet-a,subnet-b", "sg-1",
        "us-east-2", 20,
    )  # fmt: skip
    return commands


def test_the_seed_waits_for_its_task_to_stop(monkeypatch, capsys):
    commands = _run_seed(monkeypatch, _task("RUNNING"), _task("STOPPED", 0))

    start = commands.ran("aws ecs --region us-east-2 run-task")[0][0]
    assert "subnets=[subnet-a,subnet-b]" in " ".join(start)
    assert "assignPublicIp=DISABLED" in " ".join(start)
    assert len(commands.ran("aws ecs --region us-east-2 describe-tasks")) == 2
    assert "exit code 0" in capsys.readouterr().out


def test_a_failed_seed_fails_the_apply(monkeypatch):
    with pytest.raises(SystemExit, match="exit code 1.*/ecs/securepay-dev-admin"):
        _run_seed(monkeypatch, _task("STOPPED", 1))
