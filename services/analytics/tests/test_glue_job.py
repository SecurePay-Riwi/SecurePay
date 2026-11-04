"""The analytics Spark job on AWS Glue (HU-66): its entry point, the
libraries Glue installs, the code zip and the Glue catalog tables
(infra/spark/analytics_job.py, infra/spark/package.py,
infra/terraform/modules/analytics)."""

import importlib.util
import re
import tomllib
import zipfile
from pathlib import Path

from services.analytics import catalog
from services.analytics.tests.conftest import DAY, FIXTURES
from shared.analytics import PARTITION, TABLES

ROOT = Path(__file__).resolve().parents[3]
MODULES = ROOT / "infra" / "terraform" / "modules"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "infra" / "spark" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_job_args_keeps_ours_and_drops_glues():
    argv = [
        "--JOB_ID", "j_1",
        "--day", "2026-10-05",
        "--JOB_RUN_ID", "jr_1",
        "--raw", "s3://lake",
        "--output", "s3://lake",
        "--JOB_NAME", "securepay-dev-analytics",
        "--job-bookmark-option", "job-bookmark-disable",
    ]  # fmt: skip

    assert _load("analytics_job").job_args(argv) == [
        "--day", "2026-10-05", "--raw", "s3://lake", "--output", "s3://lake",
    ]  # fmt: skip


def test_the_job_builds_the_day_and_checks_its_quality(spark, tmp_path):
    result = _load("analytics_job").run(
        ["--JOB_NAME", "x", "--day", DAY.isoformat(), "--raw", str(FIXTURES),
         "--output", str(tmp_path)]
    )  # fmt: skip

    assert result["day"] == DAY.isoformat()
    assert result["tables"]["fact_decision"] > 0
    assert result["quality"]["failures"] == {}


def _default(path: Path, variable: str) -> str:
    source = path.read_text(encoding="utf-8")
    block = source[source.index(f'variable "{variable}"') :]
    return re.search(r'default\s*=\s*"([^"]+)"', block).group(1)


def test_glue_installs_the_versions_of_uv_lock():
    default = _default(MODULES / "analytics" / "variables.tf", "python_modules")
    modules = dict(item.split("==") for item in default.split(","))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package["version"] for package in lock["package"]}

    assert modules == {name: locked[name] for name in modules}
    # What the ETL imports beyond Glue's own boto3 and pyspark.
    assert {"sqlalchemy", "python-dotenv", "pydantic", "pydantic-core"} <= set(modules)


def test_the_deploy_zip_has_the_folders_terraform_zips(tmp_path):
    package = _load("package")
    source = (MODULES / "reconciliation" / "main.tf").read_text(encoding="utf-8")
    listed = re.search(r"code_folders\s*=\s*\[([^\]]*)\]", source).group(1)

    assert tuple(re.findall(r'"([^"]+)"', listed)) == package.CODE_FOLDERS

    package_zip = tmp_path / "code.zip"
    files = package.build(package_zip)
    names = zipfile.ZipFile(package_zip).namelist()
    assert names == files
    assert "services/analytics/etl.py" in names
    assert "services/reconciliation/match.py" in names
    assert "shared/analytics.py" in names
    assert not [n for n in names if "/tests/" in n]


def test_the_catalog_file_is_up_to_date():
    """Run `uv run python -m services.analytics.catalog` and commit
    infra/terraform/modules/analytics/tables.json when this fails."""
    assert catalog.OUTPUT.read_text(encoding="utf-8") == catalog.render()


def test_the_catalog_has_every_table_with_its_columns_and_partition():
    tables = catalog.glue_tables()

    assert set(tables) == set(TABLES)
    for name, table in TABLES.items():
        glue = tables[name]
        assert [c["name"] for c in glue["columns"]] == list(table.column_names)
        assert [c["type"] for c in glue["columns"]] == [c.type for c in table.columns]
        assert glue["partition"] == (PARTITION if table.partition else None)
        assert glue["location"] == f"analytics/{name}/"
        assert PARTITION not in table.column_names  # the key must not clash
