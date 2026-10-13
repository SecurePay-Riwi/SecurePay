# PagoSeguro Antifraude

Plataforma de monitoreo transaccional, reglas antifraude y conciliación
para una billetera digital.

## Descripción

PagoSeguro es una billetera digital con 2,3 millones de usuarios que
procesa 1,8 millones de transacciones diarias en 4 monedas. Este
proyecto construye una plataforma antifraude basada en reglas
configurables, con flujo de revisión de casos y conciliación diaria con
socios de pago.

## Estructura del repositorio

Monorepo: una carpeta por cada pieza que se despliega por separado.

```
services/
  decision_engine/   motor de decisión (FastAPI, POST /transactions) y sus pruebas
shared/              modelos de SQLAlchemy y conexión a PostgreSQL, usados por todos
generators/          generador de transacciones con fraude y sus pruebas
db/
  seed/              seed de PostgreSQL: usuarios, cuentas, dispositivos, comercios y listas
```

Las carpetas se nombran con guion bajo (`decision_engine`) porque Python
no puede importar módulos con guion. Más adelante se agregan los
consumidores, las APIs y las tareas programadas dentro de `services/`,
`jobs/` para PySpark e `infra/` para Terraform.

## Requisitos

-   [uv](https://docs.astral.sh/uv/getting-started/installation/) (gestor de paquetes y entornos de Python)
-   Python 3.12 (uv lo instala solo si no lo tienes)
-   PostgreSQL 16 o superior
-   [Docker Desktop](https://www.docker.com/products/docker-desktop/) (para Valkey, la caché del motor)
-   Git

## Instalación y ejecución

Desde la raíz del proyecto:

### Paso 1 --- Clonar el repo

En terminal:

``` bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
cd SecurePay
```

### Paso 2 --- Instalar dependencias

En terminal:

``` bash
uv sync
```

`uv sync` crea el entorno virtual `.venv` e instala exactamente las
versiones fijadas en `uv.lock`, incluidas las de desarrollo (pytest).
No hace falta activar el entorno: los comandos se ejecutan con
`uv run`.

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

### Paso 5 --- Levantar Valkey

El motor de decisión guarda en Valkey (en AWS es ElastiCache) la
idempotencia y el historial de transferencias de cada cuenta que usa la
regla de velocidad. En local corre en un contenedor de Docker. Con Docker
Desktop abierto:

``` bash
docker run -d --name pagoseguro-valkey -p 6379:6379 valkey/valkey:8
docker exec pagoseguro-valkey valkey-cli ping
```

El segundo comando debe responder `PONG`. La primera vez Docker avisa
`Unable to find image 'valkey/valkey:8' locally` y la descarga sola.

Después de reiniciar el equipo o cerrar Docker, el contenedor queda
apagado. Se enciende con:

``` bash
docker start pagoseguro-valkey
```

No se vuelve a crear con `docker run`: el nombre ya existe y daría
error. Cuando el repo tenga su `docker-compose.yml`, este paso se
reemplaza por `docker compose up`.

### Paso 6 --- Crear el `.env`

Copiar `.env.example` a `.env`:

``` bash
cp .env.example .env
```

Ajustar `DATABASE_URL` con el usuario y la contraseña de tu base local.
El resto de variables de `.env.example` tienen valores por defecto
válidos para desarrollo.

``` env
DATABASE_URL=postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro
VALKEY_URL=redis://localhost:6379/0
```

### Paso 7 --- Ejecutar el seed

``` bash
uv run python -m db.seed.seed
```

Debería generar:

-   100 usuarios
-   100 cuentas (una por usuario, en USD, COP, EUR o JPY)
-   150 dispositivos (146 normales y 4 compartidos entre varias cuentas)
-   50 comercios
-   20 personas en la lista restrictiva (5 son clientes)

El seed solo carga datos maestros. Las transacciones no van en el seed:
las manda el generador al motor, como lo haría el core.

### Paso 8 --- Verificar

``` bash
psql -U pagoseguro -d pagoseguro -h localhost
```

Dentro de `psql`:

``` sql
SELECT COUNT(*) FROM usuarios;
\q
```

Debería devolver `100`.

### Paso 9 --- Ejecutar el generador de transacciones

El generador hace de core de la billetera: lee las cuentas del seed una
vez y produce transacciones con patrones de fraude y defectos de calidad.
Con `GEN_OUTPUT=file` escribe los eventos en `generated/instance-0/` sin
mandarlos al motor.

``` bash
uv run python -m generators
```

Con la semilla 42 y los valores de `.env.example`, debería terminar en
`Listo: 1035 eventos`. Deja tres archivos:

-   `events.jsonl`: lo que recibiría el motor, en orden de envío
-   `labels.jsonl`: qué patrón es cada evento y qué regla debería disparar
-   `generation_report.json`: conteos por patrón, por tipo y por defecto

### Paso 10 --- Ejecutar las pruebas

Requiere haber ejecutado el seed, porque las pruebas de la API leen
cuentas y comercios de la base, y tener Valkey encendido (paso 5).
Si Valkey está apagado, las pruebas de idempotencia y de velocidad
salen como omitidas (`s`) y las de la API fallan con 503.

``` bash
uv run pytest
```

### Paso 11 --- Levantar la API

``` bash
uv run uvicorn services.decision_engine.main:app --reload
```

La API queda en http://localhost:8000 y la documentación interactiva
en http://localhost:8000/docs.

Necesita PostgreSQL y Valkey encendidos. Sin Valkey, `POST /transactions`
responde 503 ("El servicio de idempotencia no está disponible").

### Paso 12 --- Simular el flujo completo

El generador hace de core: manda cada transacción al motor por HTTP y
guarda la decisión que recibió junto a la etiqueta del evento. Con la API
levantada (paso 11) en una terminal, en otra:

``` bash
docker exec pagoseguro-valkey valkey-cli FLUSHDB
```

Limpia Valkey. Si no se hace, los ids de una corrida de hace menos de 1 h
se tratan como reenvíos y el historial de velocidad arrastra la corrida
anterior.

Luego, en PowerShell:

``` powershell
$env:GEN_OUTPUT="http"
uv run python -m generators
```

En bash: `GEN_OUTPUT=http uv run python -m generators`. También se puede
dejar `GEN_OUTPUT=http` en el `.env`.

A 50 eventos por segundo (`GEN_RATE`) tarda unos 20 segundos. Con la
semilla 42 debería terminar con `Respuestas del motor: {'200': 1023,
'404': 12}`. Los 404 son los eventos de seguridad (cambio de dispositivo y
de contraseña), que todavía no tienen endpoint.

Cada línea de `generated/instance-0/labels.jsonl` trae el patrón, la regla
que debería dispararse y lo que respondió el motor:

``` json
{"id": "...", "pattern": "VELOCITY", "is_fraud": true, "expected_rule": "velocidad",
 "response": {"status": 200, "decision": "HOLD", "reason": "Velocidad: 6 transferencias salientes en 10 minutos desde la misma cuenta."}}
```

Hoy el motor aplica dos reglas: lista restrictiva (REJECT) y velocidad
(HOLD, más de 5 transferencias P2P en 10 minutos desde la misma cuenta,
medidas con la hora del evento aunque lleguen desordenados). Con la
semilla 42, las 3 transacciones de `RESTRICTED_LIST` salen REJECT, 4
transferencias de `VELOCITY` salen HOLD (la que completa la ventana en
cada caso) y todo lo demás sale APPROVE, porque las otras reglas todavía
no existen.

## HU-04 --- Inyección de defectos

Permite generar datos de prueba con un porcentaje configurable de
defectos.

### Ejecutar con defectos

Ejemplo con 10%:

``` powershell
$env:SEED_DEFECT_PERCENTAGE="10"
$env:SEED_RESET="true"
uv run python -m db.seed.seed
```

### Ejecutar sin defectos

Por defecto el porcentaje es `0%`:

``` powershell
$env:SEED_DEFECT_PERCENTAGE="0"
$env:SEED_RESET="true"
uv run python -m db.seed.seed
```

### Tipos de defectos

El seed solo daña el formato del documento del usuario. El formato
correcto es solo dígitos (`1000000016`) y los defectos lo escriben así:

-   `PUNTOS` → `1.000.000.016`
-   `PREFIJO` → `CC 1000000016`
-   `ESPACIOS` → `" 1000000016 "`

La lista restrictiva siempre guarda el documento correcto, así que el
motor debe dejar solo los dígitos antes de buscarlo.

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
-   documento correcto (`canonico`) y cómo quedó escrito (`valor`)

El archivo se genera localmente y está incluido en `.gitignore`.
