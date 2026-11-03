"""Readers of the four partners' daily files (HU-36).

Each partner writes its file its own way (formats in
doc-website/docs/components/partner-statements.mdx). A reader turns one
file into StatementRecord (amounts with the precision of their currency,
times in UTC) and RejectedRow (a line that cannot be read, or a control
record that does not match the detail). A bad line never stops the rest
of the file.

The readers are written here on purpose: this repo never imports
securepay-csv, which writes these files (AGENTS.md, rule 4).
"""

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from shared.config import MONEDA_DECIMALES
from shared.reconciliation import (
    PARTNER_UTC_OFFSET,
    Partner,
    RejectedRow,
    StatementRecord,
)


class LineError(ValueError):
    """A line that cannot be read; the message is the rejection reason."""


@dataclass(frozen=True)
class Control:
    """What a file's control record declares, and where it is."""

    line_number: int
    raw: str
    count: int
    total: Decimal


@dataclass
class ParsedFile:
    records: list[StatementRecord]
    rejected: list[RejectedRow]


# --- Fields -----------------------------------------------------------------


def _zone(partner: Partner) -> timezone:
    return timezone(timedelta(hours=PARTNER_UTC_OFFSET[partner.value]))


def _currency(text: str) -> str:
    currency = text.strip()
    if currency not in MONEDA_DECIMALES:
        raise LineError(f"unknown currency {currency!r}")
    return currency


def _step(currency: str) -> Decimal:
    return Decimal(1).scaleb(-MONEDA_DECIMALES[currency])


def _amount(text: str, currency: str) -> Decimal:
    """A decimal amount ("88.910" -> 88.91); more decimals than the
    currency allows ("88.913", or "10.5" in JPY) is an error."""
    try:
        amount = Decimal(text.strip())
    except InvalidOperation:
        raise LineError("amount is not a number") from None
    if not amount.is_finite():
        raise LineError("amount is not a number")
    if amount <= 0:
        raise LineError("amount is not positive")
    exact = amount.quantize(_step(currency))
    if exact != amount:
        raise LineError(f"amount has more decimals than {currency} allows")
    return exact


def _minor_units(text: str, currency: str) -> Decimal:
    """An amount in minor units ("000000000002707" USD -> 27.07)."""
    digits = text.strip()
    if not digits.isdigit():
        raise LineError("amount is not a number")
    if int(digits) == 0:
        raise LineError("amount is not positive")
    return (Decimal(int(digits)) * _step(currency)).quantize(_step(currency))


def _time(text: str, fmt: str, zone: timezone) -> datetime:
    try:
        local = datetime.strptime(text.strip(), fmt)
    except ValueError:
        raise LineError("date is not valid") from None
    return local.replace(tzinfo=zone).astimezone(UTC)


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise LineError(f"{name} is missing")
    return value


def _fields(row: list[str], expected: int) -> list[str]:
    if len(row) != expected:
        raise LineError(f"expected {expected} fields, found {len(row)}")
    return row


def _control(raw: str, line_number: int, count: str, total: str) -> Control:
    try:
        return Control(line_number, raw, int(count.strip()), Decimal(total.strip()))
    except (ValueError, InvalidOperation):
        raise LineError("control record is not readable") from None


# --- Base reader ------------------------------------------------------------


class Reader:
    """Reads one partner's file. Subclasses say how a detail line and the
    control record look; the base class does the bookkeeping."""

    partner: Partner
    extension: str
    # The control total is a sum of minor units (True) or of amounts.
    total_in_minor_units = False

    def parse(self, text: str, file_name: str, statement_day: date) -> ParsedFile:
        lines = text.lstrip("﻿").splitlines()
        records, rejected = [], []
        control: Control | None = None
        control_unreadable = False
        detail_lines = 0
        readable_total = Decimal(0)

        for number, raw in enumerate(lines, start=1):
            if not raw.strip():
                continue
            kind = self.kind(raw, number)
            try:
                if kind == "skip":
                    continue
                if kind == "control":
                    control = self.control(raw, number)
                    continue
                detail_lines += 1
                record = self.detail(raw, number, file_name, statement_day)
            except LineError as error:
                rejected.append(self._reject(file_name, number, raw, str(error)))
                control_unreadable = control_unreadable or kind == "control"
                continue
            records.append(record)
            readable_total += (
                record.amount / _step(record.currency)
                if self.total_in_minor_units
                else record.amount
            )

        if not control_unreadable:
            rejected += self._check_control(
                control, detail_lines, readable_total, file_name, len(lines)
            )
        return ParsedFile(records, rejected)

    def _check_control(
        self, control, detail_lines, readable_total, file_name, last_line
    ):
        if control is None:
            return [self._reject(file_name, last_line, "", "control record is missing")]
        if control.count == detail_lines and control.total == readable_total:
            return []
        reason = (
            "control record does not match: declares "
            f"{control.count} records and total {control.total}, "
            f"the file has {detail_lines} records and total {readable_total}"
        )
        return [self._reject(file_name, control.line_number, control.raw, reason)]

    def _reject(self, file_name, number, raw, reason) -> RejectedRow:
        return RejectedRow(
            partner=self.partner.value,
            file_name=file_name,
            line_number=number,
            raw=raw,
            reason=reason,
        )

    def _record(
        self,
        file_name,
        number,
        statement_day,
        *,
        reference,
        partner_reference,
        tx_type,
        currency,
        amount,
        at,
    ) -> StatementRecord:
        return StatementRecord(
            partner=self.partner.value,
            statement_day=statement_day,
            file_name=file_name,
            line_number=number,
            pagoseguro_reference=_required(reference, "pagoseguro reference"),
            partner_reference=_required(partner_reference, "partner reference"),
            tx_type=tx_type,
            currency=currency,
            amount=amount,
            transaction_at=at,
        )

    # What each partner defines.
    def kind(self, raw: str, number: int) -> str:
        """ "detail", "control" or "skip" (a header)."""
        raise NotImplementedError

    def control(self, raw: str, number: int) -> Control:
        raise NotImplementedError

    def detail(
        self, raw: str, number: int, file_name: str, statement_day: date
    ) -> StatementRecord:
        raise NotImplementedError


def _csv_row(raw: str, delimiter: str) -> list[str]:
    return next(csv.reader([raw], delimiter=delimiter))


# --- The four partners -------------------------------------------------------


class BancoAndino(Reader):
    """CSV with commas and dot decimals, UTC with a Z, last row TOTAL:
    fecha_hora_utc,referencia_banco,referencia_pagoseguro,tipo,moneda,monto"""

    partner = Partner.BANCO_ANDINO
    extension = "csv"

    def kind(self, raw, number):
        if number == 1:
            return "skip"
        return "control" if raw.startswith("TOTAL") else "detail"

    def control(self, raw, number):
        row = _fields(_csv_row(raw, ","), 3)
        return _control(raw, number, row[1], row[2])

    def detail(self, raw, number, file_name, statement_day):
        at, bank_ref, reference, tx_type, currency, amount = _fields(
            _csv_row(raw, ","), 6
        )
        if tx_type.strip() != "RECARGA":
            raise LineError(f"unknown transaction type {tx_type.strip()!r}")
        currency = _currency(currency)
        return self._record(
            file_name,
            number,
            statement_day,
            reference=reference,
            partner_reference=bank_ref,
            tx_type="RECARGA",
            currency=currency,
            amount=_amount(amount, currency),
            at=_time(at, "%Y-%m-%dT%H:%M:%SZ", UTC),
        )


class RedCorresponsales(Reader):
    """Fixed-width TXT. H: partner(20) day(8) version(2). D (88 chars):
    local time(14) partner ref(12) PagoSeguro ref(36) type(7) currency(3)
    amount in minor units(15). T: count(8) total in minor units(18).
    Times in Bogota."""

    partner = Partner.RED_CORRESPONSALES
    extension = "txt"
    total_in_minor_units = True
    DETAIL_LENGTH = 88

    def kind(self, raw, number):
        return {"H": "skip", "T": "control"}.get(raw[:1], "detail")

    def control(self, raw, number):
        return _control(raw, number, raw[1:9], raw[9:27])

    def detail(self, raw, number, file_name, statement_day):
        if not raw.startswith("D"):
            raise LineError(f"unknown record type {raw[:1]!r}")
        if len(raw.rstrip()) != self.DETAIL_LENGTH:
            raise LineError(
                f"detail record has {len(raw.rstrip())} characters, expected {self.DETAIL_LENGTH}"
            )
        tx_type = raw[63:70].strip()
        if tx_type not in ("RECARGA", "RETIRO"):
            raise LineError(f"unknown transaction type {tx_type!r}")
        currency = _currency(raw[70:73])
        return self._record(
            file_name,
            number,
            statement_day,
            reference=raw[27:63],
            partner_reference=raw[15:27],
            tx_type=tx_type,
            currency=currency,
            amount=_minor_units(raw[73:88], currency),
            at=_time(raw[1:15], "%Y%m%d%H%M%S", _zone(self.partner)),
        )


class CajerosExpress(Reader):
    """CSV with semicolons and comma decimals, dd/mm/yyyy in Bogota, last
    row CONTROL: Fecha;Hora;Ref Cajero;Ref Billetera;Moneda;Valor"""

    partner = Partner.CAJEROS_EXPRESS
    extension = "csv"

    def kind(self, raw, number):
        if number == 1:
            return "skip"
        return "control" if raw.startswith("CONTROL") else "detail"

    def control(self, raw, number):
        row = _fields(_csv_row(raw, ";"), 3)
        return _control(raw, number, row[1], row[2].replace(",", "."))

    def detail(self, raw, number, file_name, statement_day):
        day, hour, atm_ref, reference, currency, amount = _fields(_csv_row(raw, ";"), 6)
        currency = _currency(currency)
        return self._record(
            file_name,
            number,
            statement_day,
            reference=reference,
            partner_reference=atm_ref,
            tx_type="RETIRO",
            currency=currency,
            amount=_amount(amount.replace(",", "."), currency),
            at=_time(
                f"{day.strip()} {hour.strip()}",
                "%d/%m/%Y %H:%M:%S",
                _zone(self.partner),
            ),
        )


class QrPagos(Reader):
    """TXT separated by "|", control first (#CTRL|day|count|total in minor
    units), then a header and the detail; UTC without saying so:
    ref_qr|ref_pagoseguro|comercio|moneda|monto_minimo|fecha"""

    partner = Partner.QR_PAGOS
    extension = "txt"
    total_in_minor_units = True

    def kind(self, raw, number):
        if raw.startswith("#CTRL"):
            return "control"
        return "skip" if raw.startswith("ref_qr|") else "detail"

    def control(self, raw, number):
        row = _fields(raw.split("|"), 4)
        return _control(raw, number, row[2], row[3])

    def detail(self, raw, number, file_name, statement_day):
        qr_ref, reference, _merchant, currency, units, at = _fields(raw.split("|"), 6)
        currency = _currency(currency)
        return self._record(
            file_name,
            number,
            statement_day,
            reference=reference,
            partner_reference=qr_ref,
            tx_type="QR",
            currency=currency,
            amount=_minor_units(units, currency),
            at=_time(at, "%Y-%m-%d %H:%M:%S", UTC),
        )


READERS: dict[str, Reader] = {
    reader.partner.value: reader
    for reader in (BancoAndino(), RedCorresponsales(), CajerosExpress(), QrPagos())
}
