"""The code zip of the Spark jobs on AWS Glue, the same one Terraform
builds (modules/reconciliation, archive_file): services/__init__.py and
the .py files of CODE_FOLDERS, without tests. The Deploy workflow
uploads it to s3://<artifacts>/jobs/code/securepay-jobs.zip on every
merge to main (MAG-295), so the jobs run the merged code without an
apply.

    python infra/spark/package.py securepay-jobs.zip
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Keep equal to code_folders in modules/reconciliation/main.tf
# (services/analytics/tests/test_glue_job.py checks it).
CODE_FOLDERS = ("services/reconciliation", "services/analytics", "shared")


def code_files(root: Path = ROOT) -> list[str]:
    files = ["services/__init__.py"]
    for folder in CODE_FOLDERS:
        files += sorted(
            p.relative_to(root).as_posix()
            for p in (root / folder).rglob("*.py")
            if "tests" not in p.relative_to(root).parts
        )
    return files


def build(output: Path, root: Path = ROOT) -> list[str]:
    files = code_files(root)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(root / name, name)
    return files


if __name__ == "__main__":
    written = build(Path(sys.argv[1]))
    print(f"{len(written)} files in {sys.argv[1]}")
