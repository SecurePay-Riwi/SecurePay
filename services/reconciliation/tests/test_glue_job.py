"""The reconciliation's Spark job on AWS Glue (HU-36): its entry point and
the libraries Glue installs (infra/spark/match_job.py,
infra/terraform/modules/reconciliation)."""

import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load_match_job():
    spec = importlib.util.spec_from_file_location(
        "match_job", ROOT / "infra" / "spark" / "match_job.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_job_args_keeps_ours_and_drops_glues():
    argv = [
        "--JOB_ID",
        "j_1",
        "--day",
        "2026-10-05",
        "--JOB_RUN_ID",
        "jr_1",
        "--records",
        "s3://lake/curated/extractos/fecha=2026-10-05/records.jsonl",
        "--decisions",
        "s3://lake/raw/decisiones",
        "--output",
        "s3://lake/curated/conciliacion/fecha=2026-10-05",
        "--JOB_NAME",
        "securepay-dev-reconciliation-match",
        "--job-bookmark-option",
        "job-bookmark-disable",
    ]

    assert load_match_job().job_args(argv) == [
        "--day",
        "2026-10-05",
        "--records",
        "s3://lake/curated/extractos/fecha=2026-10-05/records.jsonl",
        "--decisions",
        "s3://lake/raw/decisiones",
        "--output",
        "s3://lake/curated/conciliacion/fecha=2026-10-05",
    ]


def test_glue_installs_the_versions_of_uv_lock():
    variables = (
        ROOT / "infra" / "terraform" / "modules" / "reconciliation" / "variables.tf"
    ).read_text(encoding="utf-8")
    block = variables[variables.index('variable "python_modules"') :]
    default = re.search(r'default\s*=\s*"([^"]+)"', block).group(1)
    modules = dict(item.split("==") for item in default.split(","))

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package["version"] for package in lock["package"]}

    assert modules == {name: locked[name] for name in modules}
    assert set(modules) == {"sqlalchemy", "python-dotenv"}
