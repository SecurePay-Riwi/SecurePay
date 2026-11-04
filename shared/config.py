import os
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro"


def read_parameter(name: str) -> str:
    """The decrypted value of a SecureString parameter of Parameter Store.
    boto3 is imported here so the seed, which also imports this module,
    does not need it."""
    import boto3

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-2")
    ssm = boto3.client("ssm", region_name=region)
    return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


def database_url(environ=os.environ, read=read_parameter) -> str:
    """The connection URL of this component.

    In AWS each component has its own database user (security.mdx): the
    function only has DATABASE_USER and DATABASE_PASSWORD_PARAMETER (the
    name of the parameter, never the password) plus the host, and reads
    its password here, once per process. Locally, in CI and in the admin
    task, DATABASE_URL is used as before.

    The URL is built with URL.create(): the generated passwords may have
    characters such as # ? % or : that break a URL written by hand.
    """
    user = environ.get("DATABASE_USER")
    if not user:
        return environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

    from sqlalchemy import URL

    return URL.create(
        "postgresql",
        username=user,
        password=read(environ["DATABASE_PASSWORD_PARAMETER"]),
        host=environ["DATABASE_HOST"],
        port=int(environ.get("DATABASE_PORT", "5432")),
        database=environ.get("DATABASE_NAME", "securepay"),
        # TLS is required by the RDS parameter group; only the tests of a
        # local PostgreSQL without TLS change it.
        query={"sslmode": environ.get("DATABASE_SSLMODE", "require")},
    ).render_as_string(hide_password=False)


DATABASE_URL = database_url()

# False in AWS: there db-bootstrap creates the tables, users and grants
# (services/db_bootstrap), and the components only read and write. Their
# users do not own the tables, so create_schema() would fail there.
CREATE_SCHEMA = os.getenv("CREATE_SCHEMA", "true").lower() != "false"

# Fecha fija desde la que se calculan las fechas del seed y del generador.
# Así dos corridas dan los mismos datos sin importar el día.
FECHA_REFERENCIA = datetime(2026, 10, 1, tzinfo=UTC)

# Canales por los que llega cada tipo de operación. Los usan el generador
# (core simulado) y el ETL de Kaggle, que no deben importarse entre sí.
CANALES = {
    "P2P": ["APP", "WEB"],
    "QR": ["APP"],
    "RECARGA": ["APP", "WEB", "CORRESPONSAL"],
    "RETIRO": ["CORRESPONSAL", "CAJERO"],
}

# Decimales de cada moneda. El yen no lleva decimales.
MONEDA_DECIMALES = {"COP": 2, "USD": 2, "EUR": 2, "JPY": 0}
