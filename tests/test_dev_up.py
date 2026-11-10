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


def test_uncommitted_binary_diff_can_be_tagged(tmp_path):
    folder = tmp_path / "SecurePay"
    _clone(folder)
    (folder / ".gitattributes").write_text("*.dat text\n")
    (folder / "payload.dat").write_bytes(b"before\n")
    _git(folder, "add", ".")
    _git(
        folder,
        "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "data",
    )  # fmt: skip
    commit = _git(folder, "rev-parse", "--short", "HEAD")
    (folder / "payload.dat").write_bytes(b"after \x90\n")

    assert dev_up.image_tag(folder).startswith(f"{commit}-dirty-")


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


def _run_seed(monkeypatch, *states: str, kaggle_raw_dir: str | None = None):
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
        "us-east-2", 20, kaggle_raw_dir,
    )  # fmt: skip
    return commands


def test_the_seed_waits_for_its_task_to_stop(monkeypatch, capsys):
    commands = _run_seed(monkeypatch, _task("RUNNING"), _task("STOPPED", 0))

    start = commands.ran("aws ecs --region us-east-2 run-task")[0][0]
    assert "subnets=[subnet-a,subnet-b]" in " ".join(start)
    assert "assignPublicIp=DISABLED" in " ".join(start)
    assert len(commands.ran("aws ecs --region us-east-2 describe-tasks")) == 2
    assert "exit code 0" in capsys.readouterr().out


def test_the_seed_runs_the_image_as_it_is(monkeypatch):
    commands = _run_seed(monkeypatch, _task("STOPPED", 0))
    assert (
        "--overrides" not in commands.ran("aws ecs --region us-east-2 run-task")[0][0]
    )


def test_the_kaggle_etl_runs_in_the_admin_image(monkeypatch):
    commands = _run_seed(
        monkeypatch, _task("STOPPED", 0), kaggle_raw_dir="s3://lake/raw/kaggle"
    )

    start = commands.ran("aws ecs --region us-east-2 run-task")[0][0]
    container = json.loads(start[start.index("--overrides") + 1])["containerOverrides"][
        0
    ]
    assert container["name"] == "admin"
    assert container["command"] == ["python", "-m", "securepay_seed.kaggle_etl.etl"]
    assert container["environment"] == [
        {"name": "HIST_RAW_DIR", "value": "s3://lake/raw/kaggle"}
    ]


def test_a_failed_seed_fails_the_apply(monkeypatch):
    with pytest.raises(SystemExit, match="exit code 1.*/ecs/securepay-dev-admin"):
        _run_seed(monkeypatch, _task("STOPPED", 1))


def test_the_demo_day_starts_the_state_machine_without_waiting(monkeypatch, capsys):
    commands = Commands({"aws stepfunctions": {"stdout": "arn:execution"}})
    monkeypatch.setattr(subprocess, "run", commands)

    dev_up.main(
        ["start-day", "--state-machine", "arn:sm", "--day", "2026-10-05",
         "--region", "us-east-2"]
    )  # fmt: skip

    start = commands.ran("aws stepfunctions --region us-east-2 start-execution")
    assert len(commands.calls) == 1 and start
    args = start[0][0]
    assert args[args.index("--input") + 1] == '{"day": "2026-10-05"}'
    assert "arn:execution" in capsys.readouterr().out


def test_the_build_folder_may_come_from_the_environment(monkeypatch):
    commands = Commands(
        {
            "aws ecr describe-images": {"returncode": 254},
            "aws ecr get-login-password": {"stdout": "secret\n"},
        }
    )
    monkeypatch.setattr(subprocess, "run", commands)
    folder = "C:\\Users\\Jorge\\Proyecto PagoSeguro\\securepay-apis"
    monkeypatch.setenv("DEV_UP_CONTEXT", folder)

    dev_up.main(
        ["push", "--repository", REPO, "--tag", "abc1234", "--region", "us-east-2"]
    )

    assert commands.ran("docker build")[0][0][-1] == folder


def test_terraform_runs_the_script_without_quotes_or_paths():
    """On Windows Terraform escapes the quotes of a local-exec command, so a
    quoted path with spaces broke (first real apply, 2026-11-05)."""
    up = (SCRIPT.parents[1] / "envs" / "dev" / "up.tf").read_text()
    commands = [
        line.split("=", 1)[1] for line in up.splitlines()
        if line.strip().startswith(("command", "dev_up "))
    ]  # fmt: skip
    assert commands
    for command in commands:
        assert '\\"' not in command, command
    assert up.count("working_dir = local.scripts_dir") == 5


def test_the_engine_image_never_takes_the_terraform_state():
    # The engine is built from this repository's root while the apply holds
    # the state, which also has the database and Cognito passwords.
    ignored = (Path(__file__).parents[1] / ".dockerignore").read_text().splitlines()
    for pattern in (
        "infra/terraform/",
        "**/*.tfstate",
        "**/*.tfstate.*",
        "**/*.tfvars",
    ):
        assert pattern in ignored


def test_the_powerbi_key_goes_to_its_profile_and_never_to_the_output(
    monkeypatch, capsys
):
    commands = Commands({})
    monkeypatch.setattr(subprocess, "run", commands)
    monkeypatch.setenv("POWERBI_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("POWERBI_SECRET_ACCESS_KEY", "s3cr3t")

    dev_up.main(
        ["aws-profile", "--profile", "securepay-powerbi", "--region", "us-east-2"]
    )

    written = {args[3]: args[4] for args, _ in commands.ran("aws configure set")}
    assert written == {
        "aws_access_key_id": "AKIAEXAMPLE",
        "aws_secret_access_key": "s3cr3t",
        "region": "us-east-2",
        "output": "json",
    }
    for args, _ in commands.ran("aws configure set"):
        assert args[-2:] == ["--profile", "securepay-powerbi"]
    assert "s3cr3t" not in capsys.readouterr().out


def test_the_powerbi_key_never_reaches_the_command_line():
    up = (SCRIPT.parents[1] / "envs" / "dev" / "up.tf").read_text()
    profile = up[up.index('resource "terraform_data" "powerbi_profile"') :]
    command = next(line for line in profile.splitlines() if "command" in line)
    assert "secret" not in command and "aws_iam_access_key" not in command
