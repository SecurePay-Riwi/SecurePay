"""The load test machine's user data (infra/terraform/modules/load_runner):
it renders, it is valid bash and it runs what infra/load has."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TEMPLATE = (
    ROOT / "infra" / "terraform" / "modules" / "load_runner" / "user_data.sh.tftpl"
)
VALUES = {
    "repository": "https://github.com/SecurePay-Riwi/SecurePay.git",
    "git_ref": "main",
    "host": "securepay-dev-alb-1.us-east-2.elb.amazonaws.com",
    "bucket": "securepay-dev-artifacts-123",
}


def render() -> str:
    """What templatefile() gives: ${name} replaced, $${ left as ${."""
    text = TEMPLATE.read_text().replace("$${", "\0")
    used = set(re.findall(r"\$\{(\w+)\}", text))
    assert used == set(VALUES), used
    for name, value in VALUES.items():
        text = text.replace("${" + name + "}", value)
    return text.replace("\0", "${")


def test_every_template_variable_is_given():
    assert "${" not in render().replace("${1", "").replace("${*", "").replace(
        "${steps", ""
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_user_data_and_the_load_command_are_valid_bash(tmp_path):
    user_data = render()
    command = user_data.split("<<'SCRIPT'\n", 1)[1].split("\nSCRIPT\n", 1)[0]
    for name, text in {"user_data.sh": user_data, "securepay-load": command}.items():
        path = tmp_path / name
        path.write_text(text)
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True)
        assert result.returncode == 0, result.stderr


def test_it_runs_the_locustfile_of_the_load_group():
    user_data = render()
    assert (ROOT / "infra" / "load" / "locustfile.py").is_file()
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]
    assert any(dep.startswith("locust") for dep in groups["load"])
    assert "uv sync --only-group load" in user_data
    assert "-f infra/load/locustfile.py" in user_data
    assert f'--host "https://{VALUES["host"]}"' in user_data
    assert f"s3://{VALUES['bucket']}/load-tests/" in user_data
