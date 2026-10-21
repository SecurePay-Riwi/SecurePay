
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    documento = Column(String, unique=True, nullable=False)
    telefono = Column(String)
    fecha_nacimiento = Column(Date)
    kyc_estado = Column(String, nullable=False)
    fecha_registro = Column(DateTime, nullable=False)


class Cuenta(Base):
    __tablename__ = "cuentas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Único: cada usuario tiene una sola cuenta, en una sola moneda.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        unique=True,
        nullable=False,
    )
    moneda = Column(String(3), nullable=False)  # USD, COP, EUR o JPY
    saldo = Column(Numeric(18, 2), nullable=False)
    fecha_apertura = Column(DateTime, nullable=False)
    estado = Column(String, nullable=False)  # activa o bloqueada


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
    )
    device_fingerprint = Column(String, unique=True, nullable=False)
    user_agent = Column(String)
    ip = Column(String)
    fecha_asociacion = Column(DateTime, nullable=False)


class DispositivoCuenta(Base):
    """Un dispositivo usado en una cuenta desde una fecha.

    Permite que un mismo dispositivo aparezca en varias cuentas, que es
    lo que mide la regla de dispositivo compartido.
    """

    __tablename__ = "dispositivo_cuenta"

    dispositivo_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dispositivos.id"),
        primary_key=True,
    )
    cuenta_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cuentas.id"),
        primary_key=True,
        index=True,
    )
    fecha_asociacion = Column(DateTime, nullable=False)


class Comercio(Base):
    __tablename__ = "comercios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String, nullable=False)
    categoria = Column(String, nullable=False)
    direccion = Column(String)
    fecha_creacion = Column(DateTime, nullable=False)
    estado = Column(String, nullable=False)


class ListaRestrictiva(Base):
    __tablename__ = "listas_restrictivas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    documento = Column(String, unique=True, nullable=False)
    tipo = Column(String, nullable=False)
    fecha_inclusion = Column(Date, nullable=False)


class Transaccion(Base):
    __tablename__ = "transacciones"

    # Identificador único: también permitirá reconocer reintentos.
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Datos obligatorios de la operación.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        index=True,
    )
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dispositivos.id"),
        nullable=False,
    )
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("comercios.id"),
        nullable=False,
    )
    amount = Column(Numeric(12, 2), nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    channel = Column(String(30), nullable=False)

    # Etiqueta de referencia para validar el motor antifraude.
    is_fraud = Column(Boolean, nullable=False, default=False)
    fraud_pattern = Column(String(50), nullable=True)

    # Resultado de HU-06; estará vacío hasta evaluar la transacción.
    decision = Column(String(10), nullable=True)
    decision_reason = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Fecha de creación del registro.
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
