from sqlalchemy import Column, String, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import uuid

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

class Dispositivo(Base):
    __tablename__ = "dispositivos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    device_fingerprint = Column(String, unique=True, nullable=False)
    user_agent = Column(String)
    ip = Column(String)
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