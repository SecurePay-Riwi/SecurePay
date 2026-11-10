#!/bin/sh
# Entry point of the deployer image (infra/deployer/Dockerfile). Run from
# SecurePay with: docker compose -f compose.aws.yml run --rm deployer <command>
set -e

# Compose passes an empty value for a variable that is unset or empty in
# .env; empty, it would hide the one in securepay-csv/.env or the profile.
[ -n "$KAGGLE_API_TOKEN" ] || unset KAGGLE_API_TOKEN
[ -n "$AWS_PROFILE" ] || unset AWS_PROFILE

DEV=/work/${SECUREPAY_DIR:-SecurePay}/infra/terraform/envs/dev
CSV=/work/securepay-csv

case "${1:-help}" in
  check)
    # What the apply needs: the clones, the AWS profile and Docker.
    for repo in "${SECUREPAY_DIR:-SecurePay}" securepay-seed securepay-apis securepay-csv; do
      if [ -d "/work/$repo/.git" ]; then echo "ok      $repo"; else echo "missing $repo (clone it beside SecurePay)"; fi
    done
    for file in PS_20174392719_1491204439457_log.csv fraudTest.csv; do
      if [ -f "$CSV/data/kaggle/$file" ]; then echo "ok      Kaggle $file"; else echo "missing Kaggle $file (optional: deploy kaggle)"; fi
    done
    docker version --format 'ok      Docker {{.Server.Version}}'
    aws sts get-caller-identity --query Arn --output text | sed 's/^/ok      AWS /'
    ;;
  kaggle)
    # Only the download (KAGGLE_API_TOKEN in securepay-csv/.env or in the
    # environment): the apply uploads the CSVs to AWS itself.
    cd "$CSV"
    UV_PROJECT_ENVIRONMENT=/cache/venv-securepay-csv exec uv run python -c "
from securepay_csv.kaggle_datasets import config
from securepay_csv.kaggle_datasets.download import asegurar_descargado
for ds in config.DATASETS:
    print(asegurar_descargado(ds, config.carpeta_descarga()))
"
    ;;
  aws)
    shift
    exec aws "$@"
    ;;
  shell)
    shift
    exec bash "$@"
    ;;
  help | -h | --help)
    cat <<'TEXT'
docker compose -f compose.aws.yml run --rm deployer <command>

  check            the clones, the Kaggle CSVs, Docker and the AWS profile
  kaggle           download PaySim and fraudTest into securepay-csv/data/kaggle
  aws <args>       the AWS CLI (for example: aws configure)
  apply | plan | destroy | output | <any terraform command>
                   Terraform in SecurePay/infra/terraform/envs/dev
  shell [-c cmd]   a shell in the image
TEXT
    ;;
  *)
    cd "$DEV"
    # Quiet and fast after the first time (providers in the cache volume).
    terraform init -input=false >/dev/null
    exec terraform "$@"
    ;;
esac
