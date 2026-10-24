# PagoSeguro Antifraude

Plataforma de monitoreo transaccional, reglas antifraude y conciliación
para una billetera digital.

## Repositorios del proyecto

Este repositorio tiene el producto: el motor de decisión, los consumidores,
la infraestructura local (Docker Compose y LocalStack) y la documentación
(Docusaurus). Las fuentes de datos simuladas viven cada una en su repo:

| Repo | Qué tiene | Comando principal |
|------|-----------|-------------------|
| [`securepay-seed`](https://github.com/SecurePay-Riwi/securepay-seed) | Seed de PostgreSQL y ETL de Kaggle | `uv run python -m securepay_seed.seed` |
| [`securepay-generator`](https://github.com/SecurePay-Riwi/securepay-generator) | Generador de transacciones (hace de core) | `uv run python -m securepay_generator` |
| [`securepay-csv`](https://github.com/SecurePay-Riwi/securepay-csv) | Datasets de Kaggle y extractos de los socios | `uv run python -m securepay_csv.partner_statements` |
| [`securepay-apis`](https://github.com/SecurePay-Riwi/securepay-apis) | Servicio de listas restrictivas y tasas de cambio | `uv run uvicorn securepay_apis.restricted_list.main:app --port 8001` |

Se clonan uno al lado del otro, en la misma carpeta, y así cada repo
encuentra solo los archivos que producen los demás:

```
SecurePay-Riwi/
├── SecurePay/
├── securepay-seed/
├── securepay-generator/
├── securepay-csv/
└── securepay-apis/
```

> Las carpetas `db/`, `generators/` y `sources/` de este repo son solo un
> **respaldo** de antes de la separación. No se editan: los cambios van en
> el repo de cada fuente.

### Librería común: `securepay-shared`

`shared/` se publica en PyPI como
[`securepay-shared`](https://pypi.org/project/securepay-shared/) y los repos
de las fuentes lo instalan como dependencia (`import securepay_shared`).
Trae `models` (SQLAlchemy), `db` (conexión a PostgreSQL), `config` (variables
y constantes) y `aws` (clientes de boto3). `shared/cache.py`,
`shared/events.py` y `shared/rule_catalog.py` no van en el paquete: solo los
usa `services/`.

## Descripción

PagoSeguro es una billetera digital con 2,3 millones de usuarios que
procesa 1,8 millones de transacciones diarias en 4 monedas. Este
proyecto construye una plataforma antifraude basada en reglas
configurables, con flujo de revisión de casos y conciliación diaria con
socios de pago.

## Funcionalidades desarrolladas

El repositorio reúne los componentes trabajados hasta el momento:

- Motor antifraude con API FastAPI y reglas de decisión.
- Seed de datos maestros para PostgreSQL y generador de transacciones de prueba.
- Pruebas automatizadas para los componentes del proyecto.
- Simulación local de mensajería con SNS/SQS y almacenamiento en S3 mediante LocalStack.
- Generación de extractos de socios para el proceso de conciliación.
- Servicio simulado de listas restrictivas.
- HU-04: inyección configurable de defectos en los documentos generados por el seed.
- Integración de datasets históricos de Kaggle para cargar muestras en PostgreSQL y para el flujo independiente de carga al Data Lake.

## Requisitos

-   [uv](https://docs.astral.sh/uv/getting-started/installation/) (gestor de paquetes y entornos de Python)
-   Python 3.12 (uv lo instala solo si no lo tienes)
-   PostgreSQL 16 o superior
-   [Docker Desktop](https://www.docker.com/products/docker-desktop/) (para Valkey y LocalStack)
-   Una cuenta gratuita de [LocalStack](https://app.localstack.cloud) (plan Hobby) para su token
-   Git

## Instalación y ejecución

Cada paso dice en qué repo se ejecuta; si no lo dice, es en la raíz de `SecurePay`.

### Visión general: orden y dependencias

Orden recomendado: **1 → 2 → 3 y 4 (o el PostgreSQL de Compose) → 6 → 5 → 7 →
8 → 8c → 8b**. El `.env` (paso 6) se crea antes de levantar Docker (paso 5),
porque Compose lee de ahí el token de LocalStack. Después, cada pieza se
levanta por separado:

| Quiero... | Comando | Necesita | Paso |
|---|---|---|---|
| Instalar las dependencias | `uv sync` | Nada encendido | 2 |
| Crear los datos maestros | `uv run python -m securepay_seed.seed` (en `securepay-seed`) | PostgreSQL | 7 |
| Cargar el histórico de Kaggle en PostgreSQL | `uv run python -m securepay_seed.kaggle_etl.etl` (en `securepay-seed`) | PostgreSQL con el seed hecho y los 2 CSV | 8b |
| Subir los CSV de Kaggle al Data Lake | `uv run python -m securepay_csv.kaggle_datasets` (en `securepay-csv`) | LocalStack (y el token de Kaggle si faltan los CSV); no usa PostgreSQL | 8c |
| Generar transacciones de prueba | `uv run python -m securepay_generator` (en `securepay-generator`) | Seed hecho | 9 |
| Correr las pruebas | `uv run pytest` | Seed hecho; Valkey y LocalStack para algunas | 10 |
| Levantar el motor de decisión | `uv run uvicorn services.decision_engine.main:app --reload` | PostgreSQL y Valkey (y LocalStack para publicar) | 11 |
| Levantar los consumidores | `uv run python -m services.consumers` | LocalStack | 11b |
| Generar los extractos de los socios | `uv run python -m securepay_csv.partner_statements` (en `securepay-csv`) | Salida del generador (paso 9 o 12) | 13 |
| Levantar el servicio de listas restrictivas | `uv run uvicorn securepay_apis.restricted_list.main:app --port 8001` (en `securepay-apis`) | El archivo que exporta el seed | 14 |
| Consultar las tasas de cambio | `uv run python -m securepay_apis.exchange_rates` (en `securepay-apis`) | Internet | 15 |

### Paso 1 --- Clonar el repo

En terminal:

``` bash
git clone https://github.com/SecurePay-Riwi/SecurePay.git
git clone https://github.com/SecurePay-Riwi/securepay-seed.git
git clone https://github.com/SecurePay-Riwi/securepay-generator.git
git clone https://github.com/SecurePay-Riwi/securepay-csv.git
git clone https://github.com/SecurePay-Riwi/securepay-apis.git
cd SecurePay
```

Los cinco quedan en la misma carpeta, uno al lado del otro. Cada repo de
fuentes tiene su propio `.env.example`, su `uv sync` y su README.

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

Hay dos formas de tener PostgreSQL. Elige **una**:

-   **Opción A: instalado en tu máquina** (pasos 3 y 4). Escucha en el puerto
    **5432**.
-   **Opción B: el de Docker Compose.** Te saltas los pasos 3 y 4: se levanta
    en el paso 5 y escucha en el puerto **5433** (para no chocar con uno
    instalado).

Opción A, instalación:

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
historial de movimientos de cada cuenta que usan las reglas (`out:{cuenta}`
y `in:{cuenta}`). LocalStack
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
    el bucket del proveedor de listas `pagoseguro-proveedor-listas`
    (script `02_sources.py`, en la misma carpeta) y la tabla de DynamoDB
    `pagoseguro-exchange-rates` para las tasas de cambio (script
    `03_exchange_rates.py`).
    LocalStack no guarda nada al apagarse: cada vez que arranca, el script
    vuelve a crear todo vacío.

Para apagar: `docker compose stop`.

**Opción B (PostgreSQL de Compose).** Si no instalaste PostgreSQL, levanta
también el de Compose con `docker compose up -d postgres` (o
`docker compose up -d` para los tres servicios). Crea solo la base y el
usuario `pagoseguro` (contraseña `pagoseguro`, los valores `POSTGRES_*` del
`.env`) y escucha en el puerto **5433**: pon ese puerto en `DATABASE_URL`
(paso 6). Compose lee todo el `.env`, así que debe tener tu
`LOCALSTACK_AUTH_TOKEN` aunque solo levantes PostgreSQL. Los datos se
conservan al apagar; `docker compose down -v` los borra.

### Paso 6 --- Crear el `.env`

Copiar `.env.example` a `.env`:

``` bash
cp .env.example .env
```

Ajustar `DATABASE_URL` según la opción que elegiste en el paso 3 y pegar tu
token de LocalStack. El resto de variables de `.env.example` tienen valores
por defecto válidos para desarrollo.

``` env
# Opción A: PostgreSQL instalado en tu máquina (puerto 5432)
DATABASE_URL=postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro
# Opción B: PostgreSQL de Docker Compose (puerto 5433)
# DATABASE_URL=postgresql://pagoseguro:pagoseguro@localhost:5433/pagoseguro
VALKEY_URL=redis://localhost:6379/0
LOCALSTACK_AUTH_TOKEN=ls-...
```

Si el usuario o la contraseña de tu base son otros, cámbialos en la URL. Con
la opción B, `DATABASE_URL` y los `POSTGRES_*` del `.env` deben coincidir.

Las variables `AWS_*` apuntan a LocalStack con credenciales de mentira
(`test`), a propósito. En AWS no se ponen: el motor y las Lambdas usan su
rol.

### Paso 7 --- Ejecutar el seed (repo `securepay-seed`)

``` bash
cd ../securepay-seed
cp .env.example .env
uv sync
uv run python -m securepay_seed.seed
```

Debería generar:

-   100 usuarios
-   100 cuentas (una por usuario, en USD, COP, EUR o JPY)
-   150 dispositivos (146 normales y 4 compartidos entre varias cuentas)
-   50 comercios
-   20 personas en la lista restrictiva (5 son clientes)

Al final exporta esa lista a `generated/listas/lista_restrictiva.jsonl`,
que es la "base del proveedor" que lee el servicio de listas (paso 14).
Los defectos de formato del documento se activan con `SEED_DEFECT_PERCENTAGE`
(ver el README de `securepay-seed`).
Con `SEED_LIST_OUTPUT=s3` también la sube a LocalStack.

El seed solo carga datos maestros. Las transacciones de prueba no van en el
seed: las manda el generador al motor, como lo haría el core. El histórico
de Kaggle se carga aparte, en la tabla `transacciones`, con el paso 8b.

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

### Paso 8b --- Cargar los datasets históricos de Kaggle (repo `securepay-seed`)

Opcional y **después del seed**. Necesita los dos CSV de Kaggle, que descarga
`securepay-csv` (paso 8c); si los dos repos están uno al lado del otro, el
ETL los encuentra solo.

``` bash
cd ../securepay-seed
uv run python -m securepay_seed.kaggle_etl.etl --dry-run   # ver qué haría
uv run python -m securepay_seed.kaggle_etl.etl             # cargar
```

Detalles, variables y la huella para comprobar que todos cargan lo mismo:
README de `securepay-seed` y la página
[Kaggle datasets](https://securepay-riwi.github.io/SecurePay/docs/components/kaggle-datasets) de Docusaurus.

### Paso 8c --- Cargar PaySim y fraudTest al Data Lake (repo `securepay-csv`)

Descarga los dos datasets de Kaggle (necesita `KAGGLE_API_TOKEN` en el `.env`)
y los sube a `raw/kaggle/` en LocalStack. No usa PostgreSQL.

``` bash
cd ../securepay-csv
cp .env.example .env
uv sync
uv run python -m securepay_csv.kaggle_datasets
```

### Paso 9 --- Ejecutar el generador de transacciones

El generador hace de core de la billetera: lee las cuentas del seed una
vez y produce transacciones con patrones de fraude y defectos de calidad.
Con `GEN_OUTPUT=file` escribe los eventos en `generated/instance-0/` sin
mandarlos al motor.

``` bash
cd ../securepay-generator
cp .env.example .env
uv sync
uv run python -m securepay_generator
```

Con la semilla 42 y los valores de `.env.example`, debería terminar en
`Listo: 1036 eventos`. Deja tres archivos:

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

Cada repo de fuentes corre sus propias pruebas con `uv run pytest` y
ninguna necesita servicios, internet ni los CSV reales (las de integración
con LocalStack se omiten si no está levantado). Aquí también corren las
pruebas de las carpetas de respaldo (`db/`, `generators/`, `sources/`)
mientras existan.

PostgreSQL: el proyecto instala **Psycopg 3** (`psycopg[binary]`) y
`shared/db.py` fuerza ese controlador (`postgresql+psycopg://`) aunque tu
`DATABASE_URL` empiece por `postgresql://`. No hace falta instalar `psycopg2`.

### Paso 11 --- Levantar la API

``` bash
uv run uvicorn services.decision_engine.main:app --reload
```

La API queda en http://localhost:8000 y la documentación interactiva
en http://localhost:8000/docs.

Necesita PostgreSQL y Valkey encendidos. Sin Valkey, `POST /transactions`
responde 503 ("El servicio de idempotencia no está disponible").

`POST /security-events` stores device and password changes for the
account takeover rule (only Valkey needed; 503 without it). Events are
kept for `HISTORY_SECURITY_MINUTES` (60).

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
se tratan como reenvíos y el historial de las cuentas arrastra la corrida
anterior. Con `docker compose`, el contenedor se llama distinto:
`docker compose exec valkey valkey-cli FLUSHDB`.

Para que las decisiones lleguen hasta S3, deja corriendo también los
consumidores (paso 11b).

Luego, en PowerShell:

``` powershell
cd ../securepay-generator
$env:GEN_OUTPUT="http"
uv run python -m securepay_generator
```

En bash: `GEN_OUTPUT=http uv run python -m securepay_generator`. También se puede
dejar `GEN_OUTPUT=http` en el `.env`.

A 50 eventos por segundo (`GEN_RATE`) tarda unos 20 segundos. Con la
semilla 42 debería terminar con `Respuestas del motor: {'200': 1023,
'404': 12}`. Los 404 son los eventos de seguridad (cambio de dispositivo y
de contraseña), que todavía no tienen endpoint.

Cada línea de `securepay-generator/generated/instance-0/labels.jsonl` trae el patrón, la regla
que debería dispararse y lo que respondió el motor:

``` json
{"id": "...", "pattern": "VELOCITY", "is_fraud": true, "expected_rule": "velocity",
 "response": {"status": 200, "decision": "HOLD", "reason": "Velocity: 6 outgoing transfers in 10 minutes from the same account."}}
```

Hoy el motor aplica dos reglas: lista restrictiva (REJECT) y velocidad
(HOLD, más de 5 transferencias P2P en 10 minutos desde la misma cuenta,
medidas con la hora del evento aunque lleguen desordenados). Con la
semilla 42, las 3 transacciones de `RESTRICTED_LIST` salen REJECT, 4
transferencias de `VELOCITY` salen HOLD (la que completa la ventana en
cada caso) y todo lo demás sale APPROVE, porque las otras reglas todavía
no existen. Cada respuesta trae además `rules_triggered` (todas las reglas
que se activaron, aunque decida la más severa) y `rules_version`.

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

### Paso 13 --- Generar los extractos de los socios (repo `securepay-csv`)

Arma los archivos diarios de los 4 socios de pago a partir de la salida del
generador (paso 9 o 12), que encuentra sola en `../securepay-generator/generated`.

``` bash
cd ../securepay-csv
uv run python -m securepay_csv.partner_statements
```

Detalles: README de `securepay-csv` y la página
[Partner statements](https://securepay-riwi.github.io/SecurePay/docs/components/partner-statements).

### Paso 14 --- Levantar el servicio de listas restrictivas (repo `securepay-apis`)

Simula al proveedor externo de listas: responde lento y a veces se cae, a
propósito. Carga al arrancar el archivo que exporta el seed (paso 7), que
encuentra solo en `../securepay-seed/generated/listas/`.

``` bash
cd ../securepay-apis
cp .env.example .env
uv sync
uv run uvicorn securepay_apis.restricted_list.main:app --port 8001
```

Detalles: README de `securepay-apis` y la página
[Restricted list](https://securepay-riwi.github.io/SecurePay/docs/components/restricted-list).

### Paso 15 --- Consultar las tasas de cambio (repo `securepay-apis`)

``` bash
cd ../securepay-apis
uv run python -m securepay_apis.exchange_rates
```

Necesita internet. Detalles en la página
[Exchange rates](https://securepay-riwi.github.io/SecurePay/docs/components/exchange_rates).

### Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `Connection refused` a `localhost:5432` o `5433` | PostgreSQL apagado, o el puerto de `DATABASE_URL` no es el de tu opción: 5432 si lo instalaste (opción A), 5433 si es el de Compose (opción B). |
| `Falta LOCALSTACK_AUTH_TOKEN en el .env` al hacer `docker compose up` | Pega tu token de LocalStack en el `.env` (paso 5). |
| `POST /transactions` responde 503 | Valkey apagado: `docker compose up -d valkey` (paso 5). |
| `Could not connect to the endpoint URL` | LocalStack apagado: `docker compose up -d localstack` y `docker compose ps` (debe quedar `healthy`). |
| El ETL o los extractos no encuentran datos | Falta correr el seed (paso 7) o el generador (paso 9), o los repos no están uno al lado del otro (paso 1). |
| Aparecen columnas `V1`, `V2`... en un dataset | Es `creditcard.csv`, que el proyecto no usa. Usa `fraudTest.csv` (README de `securepay-csv`). |

## Docker: levantar el ecosistema completo (MAG-31 / MAG-32)

Clona los repositorios satélite al mismo nivel que SecurePay, abre Docker Desktop y, desde la raíz de SecurePay, crea el archivo .env a partir de .env.example. Configura LOCALSTACK_AUTH_TOKEN con tu token personal de LocalStack; nunca lo subas a Git. Compose construye imágenes desde securepay-seed, securepay-generator, securepay-csv y securepay-apis, que deben estar clonados al lado.

Valida la configuración y levanta el stack:

    docker compose config --quiet
    docker compose up --build -d
    docker compose ps

Compose coordina PostgreSQL, Valkey, LocalStack, el seed, el motor antifraude, la API de listas restrictivas, los consumidores, el generador y los extractos. El seed y el generador son tareas de una sola ejecución. El seed usa SEED_RESET=true para regenerar los datos de desarrollo al iniciar; no uses este stack contra una base de datos con datos que quieras conservar.

- Motor antifraude: http://localhost:8000/health y http://localhost:8000/docs
- API de listas restrictivas: http://localhost:8001/health
- PostgreSQL: puerto 5433; Valkey: 6379; LocalStack: 4566.

Valkey arranca vacío en cada `up` (sin persistencia), así que no hace falta `FLUSHDB` entre corridas. Las variables del motor (historial, timeout, mula) se toman del `.env` con los mismos valores por defecto que `.env.example`.

Para revisar logs o apagar los servicios:

    docker compose logs -f decision-engine
    docker compose down

Para borrar también los volúmenes persistentes usa docker compose down -v. La descarga de Kaggle es opcional y requiere KAGGLE_API_TOKEN en el .env:

    docker compose run --rm --no-deps partner-statements python -m securepay_csv.kaggle_datasets

En el workflow de GitHub Actions, la validación de arranque y health checks de Docker se ejecuta cuando está configurado el secreto de repositorio `LOCALSTACK_AUTH_TOKEN` (Settings → Secrets and variables → Actions). El token no debe guardarse en archivos versionados ni compartirse en mensajes.

## Infraestructura en AWS (Terraform)

`infra/terraform/` crea en AWS la red, los security groups, los roles IAM, los buckets S3 y RDS del diseño. Los nombres van en inglés con el prefijo `securepay-<ambiente>-`. Qué crea y por qué está en `doc-website/docs/architecture/terraform.mdx`; el paso a paso (instalar la CLI de AWS y Terraform, crear el usuario IAM y su llave, crear, revisar y destruir) está en `doc-website/docs/getting-started/deploy-aws-terraform.mdx`.

Necesitas Terraform 1.9 o más reciente, la CLI de AWS y un usuario IAM (nunca root) con `PowerUserAccess` más la política `infra/terraform/terraform-user-policy.json`. No se guardan credenciales en archivos. Desde `infra/terraform/envs/dev`:

    cp terraform.tfvars.example terraform.tfvars   # tu nombre y tu correo
    terraform init
    terraform plan       # la primera vez: 139 to add
    terraform apply
    terraform destroy    # siempre al terminar de probar: los NAT y RDS cobran aunque no haya tráfico

El estado (`terraform.tfstate`) y `terraform.tfvars` quedan en tu equipo y git los ignora. El estado guarda las contraseñas de RDS, así que no se comparte. Corre `apply` y `destroy` siempre desde el mismo equipo.
