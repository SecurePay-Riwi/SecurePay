# PagoSeguro Antifraude

Plataforma de monitoreo transaccional, reglas antifraude y conciliación para una billetera digital.

## Descripción

PagoSeguro es una billetera digital con 2,3 millones de usuarios que procesa 1,8 millones de transacciones diarias en 4 monedas. Este proyecto construye una plataforma antifraude basada en reglas configurables, con flujo de revisión de casos y conciliación diaria con socios de pago.

## Requisitos

- Python 3.10 o superior
- PostgreSQL 16 o superior
- Git

## Instalación

## Instalación y ejecucion

Desde la raíz del proyecto:

### Paso 1 — Clonar el repo
En terminal:
```bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
cd SecurePay
```

### Paso 2 — Crear el entorno virtual
En terminal:
```bash

python -m venv venv

venv\Scripts\activate          # Windows

source venv/bin/activate        # macOS/Linux

pip install -r requirements.txt
```

### Paso 3 — Descargar postgre
Windows: descargar de https://www.postgresql.org/download/windows/

macOS: brew install postgresql@16

Linux: sudo apt install postgresql-16

### Paso 4 — Crear la base de datos y el usuario
desde terminal de visual, entrar a psql como postgres:

```bash
psql -U postgres -h localhost
```

Dentro:

```bash
CREATE DATABASE pagoseguro;
CREATE USER pagoseguro WITH PASSWORD 'pagoseguro';
GRANT ALL PRIVILEGES ON DATABASE pagoseguro TO pagoseguro;
ALTER DATABASE pagoseguro OWNER TO pagoseguro;
GRANT ALL ON SCHEMA public TO pagoseguro;
\q
```

### Paso 5 — Crear el .env
Copiar .env.example a .env:
```bash
cp .env.example .env
```
Contenido:
```bash
DATABASE_URL=postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro
SEED_MODE=dev
SEED=42
SEED_RESET=false
```

### Paso 6 — Ejecutar el seed
En terminal:
```bash
python -m seeds.seed
```
Debería generar 100 usuarios, ~146 dispositivos, 50 comercios, 20 listas.

### Paso 7 — Verificar

En terminal:
```bash
psql -U pagoseguro -d pagoseguro -h localhost

SELECT COUNT(*) FROM usuarios;
\q
```
Debería devolver 100.
