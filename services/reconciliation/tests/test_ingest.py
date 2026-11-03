"""Step 1: reading the partners' files (HU-36). No database needed.

The fixture day must give exactly what tests/fixtures/curated/extractos/
says; the small files written here cover each format and each bad line.
"""

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from services.reconciliation import ingest, storage
from services.reconciliation.parsers import READERS
from services.reconciliation.tests.conftest import DAY, RECORDS, REJECTS, STATEMENTS
from shared.reconciliation import record_from_json

REF = "8826d3d4-1b2e-5a4f-a00b-38c1b3789400"
OTHER_REF = "0a15bfa4-e601-5486-b43c-d08c34e0ac14"


def _key(record):
    return (record.partner, record.file_name, record.line_number)


def _write(root, partner, name, text):
    folder = root / partner / f"fecha={DAY}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def _parse(partner, text, name="file.txt"):
    return READERS[partner].parse(text, name, DAY)


def _reasons(parsed):
    return [(r.line_number, r.reason) for r in parsed.rejected]


# --- The fixture day ---------------------------------------------------------


def test_fixture_day_gives_the_expected_records():
    records, _ = ingest.read_day(DAY, STATEMENTS)
    expected = [record_from_json(d) for d in storage.read_jsonl(RECORDS)]
    assert sorted(records, key=_key) == sorted(expected, key=_key)


def test_fixture_day_gives_the_expected_rejections():
    _, rejected = ingest.read_day(DAY, STATEMENTS)
    expected = storage.read_jsonl(REJECTS)
    # Compare partner, file and line, not the wording (fixtures README).
    assert sorted((r.partner, r.file_name, r.line_number) for r in rejected) == sorted(
        (d["partner"], d["file_name"], d["line_number"]) for d in expected
    )


def test_the_latest_version_wins():
    records, rejected = ingest.read_day(DAY, STATEMENTS)
    files = {r.file_name for r in records if r.partner == "banco_andino"}
    assert files == {"banco_andino_20261005_v2.csv"}
    # v1's control does not add up, but v1 is not read at all.
    assert not any(r.file_name.endswith("_v1.csv") and r.partner == "banco_andino" for r in rejected)


def test_run_writes_records_and_rejects(tmp_path, report):
    result = ingest.run(DAY, STATEMENTS, str(tmp_path))
    folder = tmp_path / "curated" / "extractos" / "fecha=2026-10-05"
    # Compare paths as Path: on Windows the folder comes with "\\".
    assert Path(result.pop("records_path")) == folder / "records.jsonl"
    assert result == {
        "day": "2026-10-05",
        "files_read": report["expected_run"]["files_read"],
        "records": report["expected_run"]["records"],
        "rejected": report["expected_run"]["rejected"],
    }
    assert len(storage.read_jsonl(str(folder / "records.jsonl"))) == 11
    assert len(storage.read_jsonl(str(folder / "rejects.jsonl"))) == 2


# --- Each format, clean ------------------------------------------------------


def test_banco_andino_reads_utc_and_extra_decimals():
    text = (
        "fecha_hora_utc,referencia_banco,referencia_pagoseguro,tipo,moneda,monto\n"
        f"2026-10-05T18:20:00Z,BA1,{REF},RECARGA,EUR,88.910\n"
        "TOTAL,1,88.91\n"
    )
    parsed = _parse("banco_andino", text)
    assert parsed.rejected == []
    [record] = parsed.records
    assert record.amount == Decimal("88.91") and str(record.amount) == "88.91"
    assert record.transaction_at == datetime(2026, 10, 5, 18, 20, tzinfo=UTC)
    assert (record.tx_type, record.partner_reference, record.line_number) == ("RECARGA", "BA1", 2)


def test_red_corresponsales_reads_fixed_width_bogota_time_and_minor_units():
    text = (
        "Hred_corresponsales  2026100501\n"
        f"D20261005233000RC1         {REF}RETIRO COP000000020000000\n"
        "T00000001000000000020000000\n"
    )
    parsed = _parse("red_corresponsales", text)
    assert parsed.rejected == []
    [record] = parsed.records
    assert record.amount == Decimal("200000.00")
    # 23:30 in Bogota is 04:30 UTC of the next day.
    assert record.transaction_at == datetime(2026, 10, 6, 4, 30, tzinfo=UTC)
    assert (record.tx_type, record.partner_reference) == ("RETIRO", "RC1")


def test_cajeros_express_reads_semicolons_comma_decimals_and_bogota_time():
    text = (
        "Fecha;Hora;Ref Cajero;Ref Billetera;Moneda;Valor\n"
        f"05/10/2026;20:00:00;CX1;{REF};EUR;50,00\n"
        "CONTROL;1;50,00\n"
    )
    parsed = _parse("cajeros_express", text)
    assert parsed.rejected == []
    [record] = parsed.records
    assert record.amount == Decimal("50.00")
    assert record.transaction_at == datetime(2026, 10, 6, 1, 0, tzinfo=UTC)
    assert record.tx_type == "RETIRO"


def test_qr_pagos_reads_control_first_and_jpy_without_decimals():
    text = (
        "#CTRL|2026-10-05|2|2501\n"
        "ref_qr|ref_pagoseguro|comercio|moneda|monto_minimo|fecha\n"
        f"QR1|{REF}|m1|JPY|1500|2026-10-05 09:00:00\n"
        f"QR2|{OTHER_REF}||USD|1001|2026-10-05 10:00:00\n"
    )
    parsed = _parse("qr_pagos", text)
    assert parsed.rejected == []
    jpy, usd = parsed.records
    assert str(jpy.amount) == "1500" and str(usd.amount) == "10.01"
    assert jpy.transaction_at == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    assert jpy.tx_type == "QR"


def test_an_empty_day_file_is_read_and_counts(tmp_path):
    for partner, name, text in [
        ("banco_andino", "banco_andino_20261005_v1.csv",
         "fecha_hora_utc,referencia_banco,referencia_pagoseguro,tipo,moneda,monto\nTOTAL,0,0\n"),
        ("red_corresponsales", "red_corresponsales_20261005_v1.txt",
         "Hred_corresponsales  2026100501\nT00000000000000000000000000\n"),
        ("cajeros_express", "cajeros_express_20261005_v1.csv",
         "Fecha;Hora;Ref Cajero;Ref Billetera;Moneda;Valor\nCONTROL;0;0\n"),
        ("qr_pagos", "qr_pagos_20261005_v1.txt",
         "#CTRL|2026-10-05|0|0\nref_qr|ref_pagoseguro|comercio|moneda|monto_minimo|fecha\n"),
    ]:
        _write(tmp_path, partner, name, text)
    result = ingest.run(DAY, str(tmp_path), str(tmp_path / "out"))
    assert (result["files_read"], result["records"], result["rejected"]) == (4, 0, 0)


# --- Bad lines ---------------------------------------------------------------


BANCO_HEADER = "fecha_hora_utc,referencia_banco,referencia_pagoseguro,tipo,moneda,monto\n"


@pytest.mark.parametrize(
    "line, reason",
    [
        (f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,USD", "expected 6 fields, found 5"),
        (f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,USD,N/A", "amount is not a number"),
        (f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,USD,-5.00", "amount is not positive"),
        (f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,USD,88.913", "amount has more decimals than USD allows"),
        (f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,JPY,10.5", "amount has more decimals than JPY allows"),
        (f"2026-10-32T07:45:29Z,BA1,{REF},RECARGA,USD,27.07", "date is not valid"),
        (f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,GBP,27.07", "unknown currency 'GBP'"),
        ("2026-10-05T07:45:29Z,BA1,,RECARGA,USD,27.07", "pagoseguro reference is missing"),
        (f"2026-10-05T07:45:29Z,BA1,{REF},RETIRO,USD,27.07", "unknown transaction type 'RETIRO'"),
    ],
)
def test_a_bad_line_is_rejected_and_the_rest_is_read(line, reason):
    text = (
        BANCO_HEADER
        + f"{line}\n"
        + f"2026-10-05T13:02:11Z,BA2,{OTHER_REF},RECARGA,COP,150000.00\n"
        + "TOTAL,2,150000.00\n"
    )
    parsed = _parse("banco_andino", text, "banco_andino_20261005_v1.csv")
    assert [r.pagoseguro_reference for r in parsed.records] == [OTHER_REF]
    assert _reasons(parsed) == [(2, reason)]
    assert parsed.rejected[0].raw == line
    assert parsed.rejected[0].file_name == "banco_andino_20261005_v1.csv"


def test_a_short_fixed_width_line_is_rejected():
    text = (
        "Hred_corresponsales  2026100501\n"
        "D20261005101000RC1         short\n"
        "T00000001000000000000000000\n"
    )
    parsed = _parse("red_corresponsales", text)
    assert parsed.records == []
    assert _reasons(parsed) == [(2, "detail record has 32 characters, expected 88")]


def test_minor_units_must_be_digits():
    text = (
        "#CTRL|2026-10-05|1|0\n"
        "ref_qr|ref_pagoseguro|comercio|moneda|monto_minimo|fecha\n"
        f"QR1|{REF}|m1|USD|10.01|2026-10-05 09:00:00\n"
    )
    assert _reasons(_parse("qr_pagos", text))[0] == (3, "amount is not a number")


# --- Control records -----------------------------------------------------------


def test_a_control_that_does_not_match_is_rejected_but_the_records_are_read():
    text = (
        "Fecha;Hora;Ref Cajero;Ref Billetera;Moneda;Valor\n"
        f"05/10/2026;07:00:00;CX1;{REF};USD;100,00\n"
        "CONTROL;1;101,00\n"
    )
    parsed = _parse("cajeros_express", text)
    assert len(parsed.records) == 1
    [rejected] = parsed.rejected
    assert rejected.line_number == 3 and rejected.raw == "CONTROL;1;101,00"
    assert rejected.reason.startswith("control record does not match")


def test_the_control_counts_every_detail_line_even_a_rejected_one():
    text = (
        "Fecha;Hora;Ref Cajero;Ref Billetera;Moneda;Valor\n"
        f"05/10/2026;07:00:00;CX1;{REF};USD;100,00\n"
        f"05/10/2026;08:00:00;CX2;{OTHER_REF};USD;N/A\n"
        "CONTROL;2;100,00\n"
    )
    # Two detail lines, 100.00 readable: the control matches.
    assert _reasons(_parse("cajeros_express", text)) == [(3, "amount is not a number")]


def test_a_missing_control_is_rejected():
    text = BANCO_HEADER + f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,USD,27.07\n"
    parsed = _parse("banco_andino", text)
    assert len(parsed.records) == 1
    assert _reasons(parsed) == [(2, "control record is missing")]


def test_an_unreadable_control_is_rejected_once():
    text = BANCO_HEADER + f"2026-10-05T07:45:29Z,BA1,{REF},RECARGA,USD,27.07\nTOTAL,one,27.07\n"
    assert _reasons(_parse("banco_andino", text)) == [(3, "control record is not readable")]


# --- Files ---------------------------------------------------------------------


def test_a_missing_file_is_a_rejected_row(tmp_path):
    _write(tmp_path, "qr_pagos", "qr_pagos_20261005_v1.txt",
           "#CTRL|2026-10-05|0|0\nref_qr|ref_pagoseguro|comercio|moneda|monto_minimo|fecha\n")
    records, rejected = ingest.read_day(DAY, str(tmp_path))
    assert records == []
    assert sorted((r.partner, r.file_name, r.line_number, r.reason) for r in rejected) == [
        ("banco_andino", "banco_andino_20261005_v1.csv", 0, "file missing"),
        ("cajeros_express", "cajeros_express_20261005_v1.csv", 0, "file missing"),
        ("red_corresponsales", "red_corresponsales_20261005_v1.txt", 0, "file missing"),
    ]


def test_version_10_wins_over_version_9(tmp_path):
    for version in (9, 10):
        _write(tmp_path, "banco_andino", f"banco_andino_20261005_v{version}.csv", BANCO_HEADER + "TOTAL,0,0\n")
    assert ingest.latest_file(str(tmp_path), "banco_andino", DAY).endswith("_v10.csv")


def test_another_days_file_in_the_folder_is_ignored(tmp_path):
    _write(tmp_path, "banco_andino", "banco_andino_20261004_v1.csv", BANCO_HEADER + "TOTAL,0,0\n")
    assert ingest.latest_file(str(tmp_path), "banco_andino", DAY) is None


# --- handler (Step Functions step 1) ------------------------------------------------


def test_handler_reads_the_day_of_the_event(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "STATEMENTS_SOURCE", STATEMENTS)
    monkeypatch.setattr(ingest, "RECON_DATA_DIR", str(tmp_path))
    result = ingest.handler({"day": "2026-10-05"})
    assert (result["day"], result["records"], result["rejected"]) == ("2026-10-05", 11, 2)


def test_without_a_day_it_reads_yesterday_in_bogota():
    # 04:00 UTC of the 6th is still 23:00 of the 5th in Bogota.
    assert ingest.yesterday_in_bogota(datetime(2026, 10, 6, 4, 0, tzinfo=UTC)) == date(2026, 10, 4)
    assert ingest.yesterday_in_bogota(datetime(2026, 10, 6, 7, 0, tzinfo=UTC)) == date(2026, 10, 5)


# --- S3 ----------------------------------------------------------------------------


class FakeS3:
    """The three S3 calls storage.py makes, over a dict."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def get_paginator(self, name):
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for b, k in fake.objects if b == Bucket and k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys]}

        return Paginator()


def _upload_fixture_day(client, bucket):
    from pathlib import Path

    root = Path(STATEMENTS)
    for path in root.rglob("*.*"):
        key = f"raw/extractos/{path.relative_to(root).as_posix()}"
        client.put_object(Bucket=bucket, Key=key, Body=path.read_bytes())


def test_run_reads_and_writes_s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3", fake)
    _upload_fixture_day(fake, "lake")

    result = ingest.run(DAY, "s3://lake/raw/extractos", "s3://lake")

    assert result["records_path"] == "s3://lake/curated/extractos/fecha=2026-10-05/records.jsonl"
    assert (result["files_read"], result["records"], result["rejected"]) == (4, 11, 2)
    assert ("lake", "curated/extractos/fecha=2026-10-05/rejects.jsonl") in fake.objects


def test_run_against_localstack(monkeypatch):
    """The real S3 API. Skipped without LocalStack (docker compose up -d)."""
    from botocore.exceptions import BotoCoreError, ClientError

    from shared.aws import cliente

    bucket = f"ingest-test-{uuid4().hex[:8]}"
    try:
        s3 = cliente("s3", read_timeout=30)
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    except (BotoCoreError, ClientError):
        pytest.skip("LocalStack is not available (docker compose up -d)")
    monkeypatch.setattr(storage, "_s3", s3)
    try:
        _upload_fixture_day(s3, bucket)
        result = ingest.run(DAY, f"s3://{bucket}/raw/extractos", f"s3://{bucket}")
        assert (result["files_read"], result["records"], result["rejected"]) == (4, 11, 2)
        written = storage.read_jsonl(result["records_path"])
        assert len(written) == 11
    finally:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                s3.delete_object(Bucket=bucket, Key=item["Key"])
        s3.delete_bucket(Bucket=bucket)
