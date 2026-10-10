# PagoSeguro Antifraude

Plataforma de monitoreo transaccional, reglas antifraude y conciliación
para una billetera digital.

## Descripción

PagoSeguro es una billetera digital con 2,3 millones de usuarios que
procesa 1,8 millones de transacciones diarias en 4 monedas. Este
proyecto construye una plataforma antifraude basada en reglas
configurables, con flujo de revisión de casos y conciliación diaria con
socios de pago.

## Requisitos

-   Python 3.10 o superior
-   PostgreSQL 16 o superior
-   Git

## Instalación y ejecución

Desde la raíz del proyecto:

### Paso 1 --- Clonar el repo

En terminal:

``` bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
cd SecurePay
```

### Paso 2 --- Crear el entorno virtual

En terminal:

``` bash
python -m venv venv
```

Windows:

``` bash
venv\Scripts\activate
```

macOS/Linux:

``` bash
source venv/bin/activate
```

Instalar dependencias:

``` bash
pip install -r requirements.txt
```

### Paso 3 --- Descargar PostgreSQL

Windows: https://www.postgresql.org/download/windows/

macOS:

``` bash
brew install postgresql@16
```

Linux:

``` bash
sudo apt install postgresql-16
```

### Paso 4 --- Crear la base de datos y el usuario

Desde terminal, entrar a `psql` como postgres:

``` bash
psql -U postgres -h localhost
```

Dentro de `psql`:

``` sql
CREATE DATABASE pagoseguro;
CREATE USER pagoseguro WITH PASSWORD 'pagoseguro';
GRANT ALL PRIVILEGES ON DATABASE pagoseguro TO pagoseguro;
ALTER DATABASE pagoseguro OWNER TO pagoseguro;
GRANT ALL ON SCHEMA public TO pagoseguro;
\q
```

### Paso 5 --- Crear el `.env`

Copiar `.env.example` a `.env`:

``` bash
cp .env.example .env
```

Contenido:

``` env
DATABASE_URL=postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro
SEED_MODE=dev
SEED=42
SEED_RESET=false
```

### Paso 6 --- Ejecutar el seed

``` bash
python -m seeds.seed
```

Debería generar:

-   100 usuarios
-   \~146 dispositivos
-   50 comercios
-   20 listas restrictivas

### Paso 7 --- Verificar

``` bash
psql -U pagoseguro -d pagoseguro -h localhost
```

Dentro de `psql`:

``` sql
SELECT COUNT(*) FROM usuarios;
\q
```

Debería devolver `100`.

## HU-04 --- Inyección de defectos

Permite generar datos de prueba con un porcentaje configurable de
defectos.

### Ejecutar con defectos

Ejemplo con 10%:

``` powershell
$env:SEED_DEFECT_PERCENTAGE="10"
$env:SEED_RESET="true"
python -m seeds.seed
```

### Ejecutar sin defectos

Por defecto el porcentaje es `0%`:

``` powershell
$env:SEED_DEFECT_PERCENTAGE="0"
$env:SEED_RESET="true"
python -m seeds.seed
```

### Tipos de defectos

-   `NULL` → `telefono`
-   `INVALID_FORMAT` → `email`
-   `OUT_OF_RANGE` → `fecha_nacimiento`

### Reporte de defectos

El archivo `defect_report.json` se genera automáticamente después de
ejecutar el seed.

Para consultarlo:

``` powershell
Get-Content .\defect_report.json
```

El reporte identifica:

-   `id` del registro
-   tipo de defecto
-   campo afectado

El archivo se genera localmente y está incluido en `.gitignore`.
