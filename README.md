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
  consumers/         consumidores de las colas (casos, historial, analítica), con firma de Lambda
shared/              modelos, conexión a PostgreSQL, clientes de AWS y formato del evento de decisión
generators/          generador de transacciones con fraude y sus pruebas
sources/
  csv_files/
    partner_statements/  extractos diarios de los 4 socios de pago (CSV y TXT) y sus pruebas
  apis/
    restricted_list/     servicio simulado del proveedor de listas restrictivas y sus pruebas
db/
  seed/              seed de PostgreSQL: usuarios, cuentas, dispositivos, comercios y listas
infra/
  localstack/init/   crea en LocalStack el tema SNS, las colas SQS y los buckets (Data Lake y proveedor de listas)
docker-compose.yml   PostgreSQL, Valkey y LocalStack para desarrollo local
```

Las carpetas se nombran con guion bajo (`decision_engine`) porque Python
no puede importar módulos con guion. Más adelante se agregan los
APIs y las tareas programadas dentro de `services/`, `jobs/` para
PySpark y Terraform dentro de `infra/`.

## Cómo viaja una decisión

```
core (generador) ──HTTP──▶ motor ──▶ responde al core (no espera a nadie)
                             │
                             └─ hilo de fondo ──▶ SNS "decisiones"
                                                   ├─▶ SQS "casos"      ─▶ consumidor de casos
                                                   ├─▶ SQS "historial"  ─▶ consumidor de historial
                                                   └─▶ SQS "analitica"  ─▶ consumidor de analítica ─▶ S3 raw/
```

Cada cola tiene su cola de errores (`casos-dlq`, ...): un mensaje que
falla 5 veces pasa ahí y se guarda 14 días. En AWS, SNS, SQS y S3 son los
servicios reales y los consumidores son Lambdas; en local los imita
LocalStack y los consumidores corren con
`uv run python -m services.consumers`. El código es el mismo: solo cambia
`AWS_ENDPOINT_URL`, que en local apunta a LocalStack.

## Requisitos

-   [uv](https://docs.astral.sh/uv/getting-started/installation/) (gestor de paquetes y entornos de Python)
-   Python 3.12 (uv lo instala solo si no lo tienes)
-   PostgreSQL 16 o superior
-   [Docker Desktop](https://www.docker.com/products/docker-desktop/) (para Valkey y LocalStack)
-   Una cuenta gratuita de [LocalStack](https://app.localstack.cloud) (plan Hobby) para su token
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

### Paso 5 --- Levantar Valkey y LocalStack

El motor guarda en Valkey (en AWS es ElastiCache) la idempotencia y el
historial de transferencias que usa la regla de velocidad. LocalStack
imita SNS, SQS y S3 en tu máquina: el motor publica ahí cada decisión y
los consumidores la leen. LocalStack es solo para desarrollo; en AWS se
usan los servicios reales.

1.  Crea tu cuenta en https://app.localstack.cloud (plan Hobby, gratis
    para uso no comercial) y copia tu token en
    *Settings → Auth Tokens*. Va en tu `.env` (paso 6), nunca en el repo.
2.  Si tenías el contenedor suelto de Valkey, apágalo, porque usa el
    mismo puerto 6379:

    ``` bash
    docker stop pagoseguro-valkey
    ```

3.  Con Docker Desktop abierto y el `.env` creado (paso 6):

    ``` bash
    docker compose up -d valkey localstack
    docker compose ps
    ```

    Los dos deben quedar `healthy`. LocalStack queda sano cuando terminó
    de crear el tema `decisiones`, las colas `casos`, `historial` y
    `analitica` (cada una con su `-dlq`) y el bucket
    `pagoseguro-datalake` (script `infra/localstack/init/01_messaging.py`),
    y el bucket del proveedor de listas `pagoseguro-proveedor-listas`
    (script `02_sources.py`, en la misma carpeta).
    LocalStack no guarda nada al apagarse: cada vez que arranca, el script
    vuelve a crear todo vacío.

Para apagar: `docker compose stop`. El Compose también trae PostgreSQL
(`docker compose up -d` levanta los tres) en el puerto **5433**, para no
chocar con un PostgreSQL instalado. Si lo usas en vez de los pasos 3 y 4,
pon el puerto 5433 en `DATABASE_URL`.

### Paso 6 --- Crear el `.env`

Copiar `.env.example` a `.env`:

``` bash
cp .env.example .env
```

Ajustar `DATABASE_URL` con el usuario y la contraseña de tu base local
y pegar tu token de LocalStack. El resto de variables de `.env.example`
tienen valores por defecto válidos para desarrollo.

``` env
DATABASE_URL=postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro
VALKEY_URL=redis://localhost:6379/0
LOCALSTACK_AUTH_TOKEN=ls-...
```

Las variables `AWS_*` apuntan a LocalStack con credenciales de mentira
(`test`), a propósito. En AWS no se ponen: el motor y las Lambdas usan su
rol.

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

Al final exporta esa lista a `generated/listas/lista_restrictiva.jsonl`,
que es la "base del proveedor" que lee el servicio de listas (paso 14).
Con `SEED_LIST_OUTPUT=s3` también la sube a LocalStack.

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

-   `events.jsonl`: lo que recibiría el motor, en orden de envío. Se
    escribe también con `GEN_OUTPUT=http`, porque de ahí leen los
    extractos de los socios (paso 13)
-   `labels.jsonl`: qué patrón es cada evento y qué regla debería disparar
-   `generation_report.json`: conteos por patrón, por tipo y por defecto

### Paso 10 --- Ejecutar las pruebas

Requiere haber ejecutado el seed, porque las pruebas de la API leen
cuentas y comercios de la base, y tener Valkey y LocalStack encendidos
(paso 5). Si Valkey está apagado, las pruebas de idempotencia y de
velocidad salen como omitidas (`s`) y las de la API fallan con 503. Si
LocalStack está apagado, las dos pruebas de punta a punta de la
mensajería salen omitidas; las demás de la mensajería usan SNS, SQS y S3
de mentira y no lo necesitan.

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

Cada decisión nueva se publica en SNS sin hacer esperar al core: la
petición la deja en una cola en memoria y un hilo de fondo la publica en
lotes de hasta 10. Un reenvío (mismo id) no se vuelve a publicar. Si
LocalStack (o SNS en AWS) está caído, el motor sigue respondiendo y cada
evento que no pudo publicar queda en el log con la marca
`EVENTO_NO_PUBLICADO` y el evento completo. `GET /health` muestra cuántos
eventos están pendientes, publicados y fallidos:

``` json
{"status": "ok", "messaging": {"pendientes": 0, "publicados": 1000, "fallidos": 0}}
```

### Paso 11b --- Levantar los consumidores

En otra terminal:

``` bash
uv run python -m services.consumers
```

Lee las tres colas en lotes de hasta 10 y llama a cada consumidor como lo
haría Lambda. Se puede levantar uno solo:
`uv run python -m services.consumers analitica`. Hoy hacen esto:

-   **analítica:** escribe cada lote como un archivo JSON Lines en
    `s3://pagoseguro-datalake/raw/decisiones/fecha=AAAA-MM-DD/`.
-   **casos:** lee y confirma. Crear el caso queda pendiente de decidir en
    equipo qué transacciones retenidas abren caso.
-   **historial:** lee y confirma. Los pares dispositivo–cuenta llegan con
    las reglas de historial.

Un mensaje que falla vuelve a la cola a los 30 s; a los 5 intentos pasa a
la cola de errores.

### Paso 12 --- Simular el flujo completo

El generador hace de core: manda cada transacción al motor por HTTP y
guarda la decisión que recibió junto a la etiqueta del evento. Con la API
levantada (paso 11) en una terminal, en otra:

``` bash
docker exec pagoseguro-valkey valkey-cli FLUSHDB
```

Limpia Valkey. Si no se hace, los ids de una corrida de hace menos de 1 h
se tratan como reenvíos y el historial de velocidad arrastra la corrida
anterior. Con `docker compose`, el contenedor se llama distinto:
`docker compose exec valkey valkey-cli FLUSHDB`.

Para que las decisiones lleguen hasta S3, deja corriendo también los
consumidores (paso 11b).

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

Para revisar la mensajería (el `awslocal` del contenedor de LocalStack es
el comando `aws` ya apuntado a LocalStack):

``` bash
docker compose exec localstack awslocal s3 ls s3://pagoseguro-datalake/raw/decisiones/ --recursive
docker compose exec localstack awslocal sqs get-queue-attributes --queue-url http://localhost:4566/000000000000/analitica-dlq --attribute-names ApproximateNumberOfMessages
```

Con la semilla 42 y los consumidores corriendo, `GET /health` termina en
`publicados: 1000` (1.023 respuestas menos los 23 reenvíos), los archivos
de `raw/decisiones/` suman 1.000 líneas, una por transacción, y las colas
y sus `-dlq` quedan en 0.

### Paso 13 --- Generar los extractos de los socios

Cada día, los 4 socios de pago (un banco y tres redes) mandan un archivo
con lo que pasó por ellos, cada uno en su formato, para la conciliación.
El generador de extractos los arma a partir de la salida del generador de
transacciones, así cuadran con lo que vio el motor. Corre primero el
paso 9 (o el 12) y luego:

``` bash
uv run python -m sources.csv_files.partner_statements
```

Con la semilla 42, después del paso 9 debería decir `598 operaciones pasan
por algún socio` y `Listo: 47 archivos`. Después del paso 12 son 595,
porque las rechazadas y retenidas no movieron dinero y el socio no las ve.

Solo entran recargas, retiros y pagos QR (las P2P son internas de la
billetera). Cada socio ve lo suyo según el tipo y el canal:

| Socio | Qué ve | Formato | Fechas |
|---|---|---|---|
| `banco_andino` | Recargas por APP y WEB | CSV con comas, fila final `TOTAL` | UTC |
| `red_corresponsales` | Recargas y retiros en CORRESPONSAL | TXT de ancho fijo (registros H, D y T), montos en unidades mínimas | Bogotá (UTC−5) |
| `cajeros_express` | Retiros en CAJERO | CSV con punto y coma y coma decimal, línea final `CONTROL` | Bogotá (UTC−5) |
| `qr_pagos` | Pagos QR | TXT separado por `\|`, control en la primera línea, unidades mínimas | UTC |

Los archivos quedan en
`generated/extractos/<socio>/fecha=AAAA-MM-DD/<socio>_AAAAMMDD_vN.<ext>`,
así que cada día llegan los 4 archivos, uno de cada socio (aunque venga
vacío), más un `_v2` cuando el socio reenvía con correcciones. El día es
el de la zona horaria del socio.

Defectos que pide el enunciado, con porcentaje configurable en el `.env`:

| Variable | Defecto | Por defecto |
|---|---|---|
| `EXT_MISSING_PCT` | El socio no reporta una transacción nuestra | 2 |
| `EXT_EXTRA_PCT` | El socio reporta una operación que PagoSeguro no tiene | 1 |
| `EXT_ROUNDING_PCT` | El socio redondea el monto a la unidad | 3 |
| `EXT_RESEND_PCT` | El socio reenvía el archivo del día (`_v2`) corrigiendo faltantes y redondeos | 10 (de los archivos con algo que corregir) |
| `EXT_BAD_CONTROL_PCT` | El registro de control no cuadra con el detalle | 10 (de los archivos) |

La otra zona horaria no es un porcentaje: dos socios escriben sus fechas
en hora de Bogotá.

`generated/extractos/extracts_report.json` es la hoja de respuestas: cada
defecto inyectado y, en `expected_differences`, lo que la conciliación
debería encontrar contra la última versión de cada día
(`MISSING_IN_PARTNER`, `MISSING_IN_PAGOSEGURO` o `AMOUNT_MISMATCH`).

Para subirlos también a la capa raw del Data Lake, con LocalStack
encendido (paso 5):

``` powershell
$env:EXT_OUTPUT="s3"
uv run python -m sources.csv_files.partner_statements
```

En bash: `EXT_OUTPUT=s3 uv run python -m sources.csv_files.partner_statements`.
Quedan en `s3://pagoseguro-datalake/raw/extractos/<socio>/fecha=AAAA-MM-DD/`:

``` bash
docker compose exec localstack awslocal s3 ls s3://pagoseguro-datalake/raw/extractos/ --recursive
```

### Paso 14 --- Levantar el servicio de listas restrictivas

Simula al proveedor externo de listas restrictivas (sanciones y PEP):
responde lento y a veces se cae, a propósito, para que el motor tenga
que defenderse. No lee PostgreSQL: carga una sola vez al arrancar el
archivo que exporta el seed (paso 7). Si vuelves a correr el seed con
otros parámetros, reinicia el servicio.

``` bash
uv run uvicorn sources.apis.restricted_list.main:app --port 8001
```

Al arrancar debe decir `Lista restrictiva cargada: 20 personas`. Si no
encuentra el archivo, no arranca y te pide correr el seed.

| Endpoint | Para qué | Respuesta |
|---|---|---|
| `GET /lista` | La lista completa. La usará la tarea diaria que carga la lista en la caché del motor | `{"total": 20, "registros": [...]}` |
| `GET /lista/{documento}` | Si un documento está listado. El motor la usará solo si la caché no está disponible | `{"listado": true, "documento": "...", "tipo": "PEP", "fecha_inclusion": "..."}` o `{"documento": "...", "listado": false}` |
| `GET /health` | Que el servicio esté vivo, sin latencia ni caídas | `{"status": "ok", "total": 20}` |

El documento se normaliza a solo dígitos, así que `CC 1.000.000.016` y
`1000000016` dan lo mismo. Que un documento no esté listado es un 200
con `"listado": false`, no un 404.

Prueba rápida (en PowerShell usa `curl.exe`):

``` bash
curl http://localhost:8001/lista/1000000016
```

Lo que lo hace "malo", configurable en el `.env`:

| Variable | Qué hace | Por defecto |
|---|---|---|
| `LISTA_LATENCIA_MIN_MS` / `LISTA_LATENCIA_MAX_MS` | Cada respuesta tarda un tiempo al azar entre estos dos valores | 50 / 3000 |
| `LISTA_FALLA_PCT` | Porcentaje de peticiones que responden 503 (proveedor caído), después de la espera | 5 |
| `LISTA_SEMILLA` | Fija el azar para repetir el mismo comportamiento | sin semilla |

Para leer la lista desde S3 como en AWS, con LocalStack encendido
(paso 5), primero súbela con el seed y luego arranca el servicio:

``` powershell
$env:SEED_LIST_OUTPUT="s3"
uv run python -m db.seed.seed
$env:LISTA_SOURCE="s3"
uv run uvicorn sources.apis.restricted_list.main:app --port 8001
```

En bash: `SEED_LIST_OUTPUT=s3 uv run python -m db.seed.seed` y
`LISTA_SOURCE=s3 uv run uvicorn sources.apis.restricted_list.main:app --port 8001`.
Si LocalStack ya estaba encendido antes de esta versión, reinícialo
(`docker compose restart localstack`) para que cree el bucket
`pagoseguro-proveedor-listas`.

Hoy el motor todavía busca la lista en PostgreSQL. Pasarlo a la caché,
con este servicio como respaldo y circuit breaker, es la historia de
rechazo por lista restrictiva del sprint 2.

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
