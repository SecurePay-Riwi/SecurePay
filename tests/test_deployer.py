"""infra/deployer and compose.aws.yml: the container that brings dev up on
AWS with only Git and Docker Desktop on the computer (MAG-308)."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCKERFILE = (ROOT / "infra" / "deployer" / "Dockerfile").read_text()


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_the_image_has_a_terraform_the_configuration_accepts():
    image = re.search(r"TERRAFORM_VERSION=([\d.]+)", DOCKERFILE).group(1)
    versions = (
        ROOT / "infra" / "terraform" / "envs" / "dev" / "versions.tf"
    ).read_text()
    low, high = re.search(
        r'required_version = ">= ([\d.]+), < ([\d.]+)"', versions
    ).groups()
    assert _version(low) <= _version(image) < _version(high)


def test_the_image_has_every_tool_the_apply_runs():
    # up.tf runs dev_up.py with uv, which calls git, docker (with buildx for
    # --provenance=false) and the AWS CLI.
    for tool in (
        "astral-sh/uv",
        "git",
        "docker-ce-cli",
        "docker-buildx-plugin",
        "awscli",
        "terraform",
    ):
        assert tool in DOCKERFILE, tool


def test_compose_gives_the_clones_the_aws_profile_and_docker():
    compose = (ROOT / "compose.aws.yml").read_text()
    for volume in (
        "- ..:/work",  # the folder that holds every clone
        ":/root/.aws",
        "- /var/run/docker.sock:/var/run/docker.sock",
        ":/cache",
    ):
        assert volume in compose, volume


def test_the_guide_is_the_same_in_the_readme_and_the_docs():
    def commands(text: str) -> list[str]:
        return re.findall(r"docker compose -f compose\.aws\.yml run [^\n`]+", text)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    intro = (ROOT / "doc-website" / "docs" / "intro.mdx").read_text(encoding="utf-8")
    assert commands(readme) and commands(readme) == commands(intro)
