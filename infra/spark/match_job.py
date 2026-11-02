"""Entry point of the reconciliation's Spark job on AWS Glue 6.0 (HU-36).

Step Functions starts the Glue job with --day --records --decisions
--output (modules/reconciliation). Glue adds arguments of its own
(--JOB_NAME, --JOB_RUN_ID, ...), so only ours go on to match.main. Our code
comes in --extra-py-files (a zip Terraform builds from
services/reconciliation and shared) and its libraries in
--additional-python-modules.
"""

import argparse
import sys

OURS = ("--day", "--records", "--decisions", "--output")


def job_args(argv: list[str]) -> list[str]:
    """Our four arguments out of everything Glue passes, in match.main's form."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in OURS:
        parser.add_argument(name, required=True)
    known, _ = parser.parse_known_args(argv)
    return [part for name in OURS for part in (name, getattr(known, name[2:]))]


if __name__ == "__main__":
    print(f"Python {sys.version}", flush=True)
    from services.reconciliation.match import main

    main(job_args(sys.argv[1:]))
