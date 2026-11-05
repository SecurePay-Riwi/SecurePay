"""What `terraform apply` in envs/dev runs on the computer that applies it.

Terraform calls this file, never a person:

    tags      the image tag of each repository, for data "external"
              (reads the query from stdin, prints one JSON object)
    push      builds an image and pushes it to ECR, unless the tag is
              already there (ECR tags are immutable)
    run-task  runs a Fargate task and fails if its container fails (the
              seed)

Only the standard library and the docker and aws commands: it runs with
`uv run --no-project python`, outside the project's environment, on
Windows (cmd) and on Linux alike.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

# The other repositories Terraform builds, by ECR repository: cloned
# beside SecurePay (AGENTS.md), each with its Dockerfile. The engine is
# SecurePay itself.
SIBLINGS = {"admin": "securepay-seed", "apis": "securepay-apis"}


def _run(*args: str, input: str | None = None, check: bool = True) -> str:
    result = subprocess.run(
        args, input=input, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise SystemExit(
            f"{' '.join(args[:3])} ... failed ({result.returncode}):\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def image_tag(folder: Path) -> str:
    """The short commit; with uncommitted changes, the commit plus a hash
    of them, so a changed folder never reuses a pushed tag. "" when the
    folder is not a git clone (that image is not built)."""
    if not folder.is_dir():
        return ""
    git = ("git", "-C", str(folder))
    probe = subprocess.run(
        (*git, "rev-parse", "--short", "HEAD"), capture_output=True, text=True
    )
    if probe.returncode != 0:
        return ""
    commit = probe.stdout.strip()
    status = _run(*git, "status", "--porcelain")
    if not status:
        return commit
    changes = status + _run(*git, "diff", "HEAD")
    return f"{commit}-dirty-{hashlib.sha256(changes.encode()).hexdigest()[:7]}"


def tags(query: dict) -> dict:
    """{"engine": tag, "admin": tag, "apis": tag} ("" for a missing clone)."""
    securepay = Path(query["securepay"]).resolve()
    found = {"engine": image_tag(securepay)}
    for name, folder in SIBLINGS.items():
        found[name] = image_tag(securepay.parent / folder)
    return found


def push(repository: str, tag: str, context: str, region: str) -> None:
    name = repository.split("/", 1)[1]
    found = subprocess.run(
        (
            "aws", "ecr", "describe-images", "--region", region,
            "--repository-name", name, "--image-ids", f"imageTag={tag}",
        ),
        capture_output=True, text=True,
    )  # fmt: skip
    if found.returncode == 0:
        print(f"{name}:{tag} is already in ECR")
        return

    password = _run("aws", "ecr", "get-login-password", "--region", region)
    # The password goes through stdin: PowerShell alters text piped
    # between programs, and it never shows in a process list.
    _run(
        "docker", "login", "--username", "AWS", "--password-stdin",
        repository.split("/", 1)[0], input=password,
    )  # fmt: skip
    image = f"{repository}:{tag}"
    # --provenance=false: Lambda rejects the image index Docker Desktop
    # pushes with an attestation.
    subprocess.run(
        ("docker", "build", "--provenance=false", "-t", image, context), check=True
    )
    subprocess.run(("docker", "push", image), check=True)
    print(f"pushed {image}")


def run_task(
    cluster: str,
    task_definition: str,
    subnets: str,
    security_group: str,
    region: str,
    timeout_minutes: int,
) -> None:
    network = (
        f"awsvpcConfiguration={{subnets=[{subnets}],"
        f"securityGroups=[{security_group}],assignPublicIp=DISABLED}}"
    )
    aws = ("aws", "ecs", "--region", region)
    task = _run(
        *aws, "run-task", "--cluster", cluster, "--launch-type", "FARGATE",
        "--task-definition", task_definition, "--network-configuration", network,
        "--query", "tasks[0].taskArn", "--output", "text",
    )  # fmt: skip
    print(f"started {task}")

    deadline = time.monotonic() + timeout_minutes * 60
    while True:
        described = json.loads(
            _run(*aws, "describe-tasks", "--cluster", cluster, "--tasks", task)
        )["tasks"][0]
        if described["lastStatus"] == "STOPPED":
            break
        if time.monotonic() > deadline:
            raise SystemExit(f"{task} did not stop in {timeout_minutes} minutes")
        time.sleep(10)

    container = described["containers"][0]
    code = container.get("exitCode")
    if code != 0:
        reason = container.get("reason") or described.get("stoppedReason", "")
        raise SystemExit(
            f"{task_definition} ended with exit code {code} {reason}; "
            f"its log: aws logs tail /ecs/{task_definition}"
        )
    print(f"{task_definition} ended with exit code 0")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tags")

    p = commands.add_parser("push")
    p.add_argument("--repository", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--context", required=True)
    p.add_argument("--region", required=True)

    t = commands.add_parser("run-task")
    t.add_argument("--cluster", required=True)
    t.add_argument("--task-definition", required=True)
    t.add_argument("--subnets", required=True)
    t.add_argument("--security-group", required=True)
    t.add_argument("--region", required=True)
    t.add_argument("--timeout-minutes", type=int, default=20)

    args = parser.parse_args(argv)
    if args.command == "tags":
        print(json.dumps(tags(json.load(sys.stdin))))
    elif args.command == "push":
        push(args.repository, args.tag, args.context, args.region)
    else:
        run_task(
            args.cluster,
            args.task_definition,
            args.subnets,
            args.security_group,
            args.region,
            args.timeout_minutes,
        )


if __name__ == "__main__":
    main()
