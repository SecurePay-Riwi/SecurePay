# Seed de datos — PagoSeguro Antifraude

Genera datos sintéticos reproducibles para el desarrollo local: usuarios, dispositivos, comercios y listas restrictivas.

## ¿Qué hace?

Puebla la base de datos PostgreSQL con datos de prueba que simulan el entorno real de PagoSeguro. Los datos son:

- **Reproducibles:** con la misma semilla, genera exactamente los mismos datos.
- **Idempotentes:** ejecutarlo varias veces no duplica registros.
- **Parametrizables:** el volumen se ajusta con variables de entorno.
- **Con integridad referencial:** los dispositivos siempre pertenecen a un usuario existente.

## Requisitos

- Python 3.10+
- PostgreSQL 16+
- Entorno virtual activo (`venv/`)

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

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate        # macOS/Linux
pip install -r requirements.txt