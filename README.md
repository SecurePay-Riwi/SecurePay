# PagoSeguro Antifraude

Plataforma de monitoreo transaccional, reglas antifraude y conciliación
para una billetera digital.

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

## Datasets históricos (Kaggle)

El ETL de PostgreSQL utiliza dos datasets históricos para cargar una muestra de transacciones en la tabla `transacciones`. Los CSV pesan cientos de MB, por lo que **no se guardan en Git**. Descárgalos y guárdalos en `data/kaggle/` en la raíz del proyecto.

| Dataset | Página en Kaggle | Archivo requerido |
|---|---|---|
| PaySim (transacciones financieras sintéticas) | [kaggle.com/datasets/ealaxi/paysim1](https://www.kaggle.com/datasets/ealaxi/paysim1) | `PS_20174392719_1491204439457_log.csv` |
| Fraud Detection | [kaggle.com/datasets/kartik2112/fraud-detection](https://www.kaggle.com/datasets/kartik2112/fraud-detection) | `fraudTest.csv` |

### Cómo descargar y ubicar los CSV

1. Inicia sesión en [Kaggle](https://www.kaggle.com).
2. Abre los enlaces anteriores, descarga los datasets y descomprime los ZIP.
3. En la raíz del proyecto, crea la carpeta `data/kaggle/` si todavía no existe.
4. Copia allí los dos archivos con sus nombres originales:

```text
data/kaggle/PS_20174392719_1491204439457_log.csv
data/kaggle/fraudTest.csv
```

No cambies los nombres de los archivos. No es necesario subirlos a GitHub ni incluirlos en un commit.

### Descarga alternativa por terminal

Si tienes instalada la [Kaggle CLI](https://github.com/Kaggle/kaggle-api) y configurado el token de tu cuenta en `~/.kaggle/kaggle.json`, puedes ejecutar:

```bash
mkdir -p data/kaggle
kaggle datasets download -d ealaxi/paysim1 -p data/kaggle --unzip
kaggle datasets download -d kartik2112/fraud-detection -f fraudTest.csv -p data/kaggle --unzip
```

### Verificar que Git ignora los CSV

Desde la raíz del repositorio:

```bash
git check-ignore -v data/kaggle/fraudTest.csv data/kaggle/PS_20174392719_1491204439457_log.csv
git status --short
```

El primer comando debe mostrar la regla de `.gitignore` que excluye los archivos. `git status` no debe listar los CSV. La carpeta `data/kaggle/` es local y no se publica en GitHub.

### Dos flujos distintos de uso de Kaggle

- **ETL de PostgreSQL (paso 8b):** usa `PS_20174392719_1491204439457_log.csv` y `fraudTest.csv`, ubicados en `data/kaggle/` (la misma carpeta de la carga al Data Lake: se descargan una sola vez). Carga una muestra en la tabla `transacciones`.
- **Carga al Data Lake (paso 8c):** usa PaySim y `fraudTest.csv` (Sparkov), ubicados en `data/kaggle/`. No usa PostgreSQL ni modifica sus tablas.

`fraudTest.csv` y `creditcard.csv` son datasets diferentes y no se sustituyen entre sí. Si ejecutas ambos flujos, revisa la ubicación que requiere cada uno; no es necesario guardar los CSV en Git.

Para cargar una muestra de los datasets históricos en PostgreSQL, sigue el [Paso 8b](#paso-8b-----cargar-los-datasets-históricos-de-kaggle-etl).

## Instalación y ejecución

Todos los comandos se ejecutan desde la raíz del proyecto.

### Visión general: orden y dependencias

Orden recomendado: **1 → 2 → 3 y 4 (o el PostgreSQL de Compose) → 6 → 5 → 7 →
8 → 8b → 8c**. El `.env` (paso 6) se crea antes de levantar Docker (paso 5),
porque Compose lee de ahí el token de LocalStack. Después, cada pieza se
levanta por separado:

| Quiero... | Comando | Necesita | Paso |
|---|---|---|---|
| Instalar las dependencias | `uv sync` | Nada encendido | 2 |
| Crear los datos maestros | `uv run python -m db.seed.seed` | PostgreSQL | 7 |
| Cargar el histórico de Kaggle en PostgreSQL | `uv run python -m db.datasets.etl` | PostgreSQL con el seed hecho y los 2 CSV | 8b |
| Subir los CSV de Kaggle al Data Lake | `uv run python -m sources.csv_files.kaggle` | LocalStack (y el token de Kaggle si faltan los CSV); no usa PostgreSQL | 8c |
| Generar transacciones de prueba | `uv run python -m generators` | Seed hecho | 9 |
| Correr las pruebas | `uv run pytest` | Seed hecho; Valkey y LocalStack para algunas | 10 |
| Levantar el motor de decisión | `uv run uvicorn services.decision_engine.main:app --reload` | PostgreSQL y Valkey (y LocalStack para publicar) | 11 |
| Levantar los consumidores | `uv run python -m services.consumers` | LocalStack | 11b |
| Generar los extractos de los socios | `uv run python -m sources.csv_files.partner_statements` | Salida del generador (paso 9 o 12) | 13 |
| Levantar el servicio de listas restrictivas | `uv run uvicorn sources.apis.restricted_list.main:app --port 8001` | El archivo que exporta el seed | 14 |
| Consultar las tasas de cambio | `uv run python -m sources.apis.exchange_rates` | Internet | 15 |

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

### Paso 8b --- Cargar los datasets históricos de Kaggle (ETL)

Es opcional y va **después del seed** (paso 7): el ETL reparte las
transacciones de Kaggle entre los usuarios, dispositivos y comercios que el
seed ya creó, así que sin seed no tiene a quién asignarlas. Además necesitas
los dos CSV en `data/kaggle/` (ver "Datasets históricos (Kaggle)").

``` bash
# 1. Ver qué haría, sin escribir nada en la base de datos
uv run python -m db.datasets.etl --dry-run

# 2. Cargar las transacciones
uv run python -m db.datasets.etl
```

Puede tardar desde unos segundos hasta un par de minutos según el computador,
porque lee las 6,3 millones de filas de PaySim.
Solo **lee** usuarios, dispositivos y comercios, y solo **escribe** en la tabla
`transacciones`. Se puede correr varias veces: no duplica nada. La
semilla (`SEED`, 42) es la misma del seed y del generador.

Con el modo `dev` y los valores por defecto, esto es lo que debe ver (los
conteos y la huella salen de una corrida real):

``` text
1/4 Verificando los CSV en data/kaggle ...
  PS_20174392719_1491204439457_log.csv: SHA-256 OK
  fraudTest.csv: SHA-256 OK
...
Huella SHA-256 del lote (70,000 filas): 91cd7780583096db95f351cb09825a96515f87a065fe328ef94c42c85347cbf8
4/4 Cargando en la tabla transacciones...
  insertadas: 70,000  |  ya existían: 0
```

Para comprobarlo en la base (con la opción B agrega `-p 5433`):

``` bash
psql -U pagoseguro -d pagoseguro -h localhost
```

``` sql
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_fraud) AS fraudes FROM transacciones;
\q
```

Debe devolver `70000` y `2100` (50.000 + 20.000 filas, con 3 % de fraude).
Si vuelves a correr el ETL, dice `insertadas: 0 | ya existían: 70,000`.

#### Qué hace, y por qué

1.  **Verifica el SHA-256 de los CSV.** Con otra versión del archivo la
    muestra saldría distinta, así que si el hash no coincide con el del
    equipo se detiene y lo dice.
2.  **Toma una muestra fija de cada dataset:** 50.000 filas de PaySim y 20.000
    de fraudTest, con **3 % de fraude** en cada una. El fraude se fija a
    propósito: al azar sería de 0,13 % (PaySim) y 0,39 % (fraudTest) y el
    motor antifraude casi no tendría casos con qué validarse.
3.  **Se queda solo con lo que `transacciones` puede guardar** (tabla de
    abajo) y descarta las filas con monto 0 (16 en PaySim), que no son pagos
    válidos.
4.  **Liga cada titular del dataset a un usuario del seed.** El titular es la
    tarjeta en fraudTest (`cc_num`) y la cuenta origen en PaySim
    (`nameOrig`). La primera vez que aparece se le asigna al azar un usuario
    que ya existía en esa fecha, y todas sus transacciones siguientes van a
    ese mismo usuario: es la forma en que el equipo relaciona los datasets
    con los usuarios, como pide el enunciado (una tarjeta vinculada a la
    billetera). Un usuario puede tener varias tarjetas, porque fraudTest trae
    más tarjetas que usuarios el seed en modo `dev`. En PaySim casi cada
    cuenta origen aparece una sola vez (6,35 millones de cuentas en 6,36
    millones de filas), así que ahí el efecto es casi nulo.
5.  **Genera lo que falta con la semilla:** dispositivo (uno propio del
    usuario), comercio y canal. Es reproducible porque el azar sale siempre de
    la misma semilla y se consume en el mismo orden.
6.  **Mantiene los datos coherentes:** ninguna transacción es anterior a la
    existencia de su dispositivo ni del comercio, y se usan solo
    dispositivos de uso propio, para no alterar los casos de dispositivo
    compartido del seed.
7.  **Inserta con IDs deterministas** (`uuid5` de la fila de origen), por eso
    repetir el ETL no duplica y cada transacción se puede rastrear hasta su
    fila del CSV.

| Columna de `transacciones` | PaySim | fraudTest |
|---|---|---|
| `amount` | `amount` | `amt` |
| `is_fraud` | `isFraud` | `is_fraud` |
| `transaction_date` | `step` (la hora 1 queda 31 días antes de la fecha de referencia; minutos y segundos se sortean) | `trans_date_trans_time`, corrida para terminar justo antes de la fecha de referencia (los datos son de 2020 y ningún usuario del seed existía) |
| `channel` | según `type`: TRANSFER → P2P, PAYMENT → QR, CASH_IN → RECARGA, CASH_OUT y DEBIT → RETIRO, con los canales que usa el generador para cada uno | categorías `*_net` → WEB; el resto → APP |
| `merchant_id` | comercio activo al azar | comercio activo de la categoría equivalente (las 14 de fraudTest se agrupan en las 5 del seed; ver `CATEGORIA_FRAUDTEST`) |
| `user_id` | el usuario ligado a la cuenta origen (`nameOrig`) | el usuario ligado a la tarjeta (`cc_num`) |
| `device_id` | un dispositivo propio de ese usuario que ya existía | un dispositivo propio de ese usuario que ya existía |
| `fraud_pattern` | `kaggle_paysim_<type>` (solo en fraudes) | `kaggle_fraudtest_<category>` (solo en fraudes) |

No se guardan los saldos de PaySim ni los demás campos de fraudTest (el número
de tarjeta, que solo se usa para ligarla al usuario, nombre, dirección, etc.)
porque `transacciones` no tiene dónde ponerlos.
Los montos se cargan tal cual vienen de Kaggle, sin convertirlos a la moneda
de la cuenta: la tabla no guarda moneda.

#### Comprobar que todos obtienen los mismos datos

Al terminar, el ETL imprime una **huella SHA-256 del lote**. Con los mismos
CSV, el mismo seed, la misma semilla y los valores por defecto de abajo, debe
salir exactamente esta (modo `dev`: 100 usuarios, 50 comercios):

```
91cd7780583096db95f351cb09825a96515f87a065fe328ef94c42c85347cbf8
```

Ese valor se obtuvo en Linux con PostgreSQL 16. Si a alguien le sale otro:

1.  Revisen el SHA-256 de los CSV (el ETL ya lo hace y avisa).
2.  Revisen que el `.env` sea el mismo (`SEED`, `SEED_MODE`, `SEED_USERS`...) y
    que la base se haya sembrado desde cero con `SEED_RESET=true`.
3.  Revisen que nadie haya cambiado las variables `HIST_*` de abajo.
4.  Ejecuten `uv sync` para tener las mismas versiones de `uv.lock`.

#### Variables opcionales

Si las cambian, **todos deben usar los mismos valores** y la huella cambiará.

| Variable | Por defecto | Qué controla |
|---|---|---|
| `HIST_PAYSIM_FILAS` | 50000 | Transacciones que se toman de PaySim |
| `HIST_PAYSIM_FRAUDE_PCT` | 3 | Porcentaje de ellas que son fraude |
| `HIST_FRAUDTEST_FILAS` | 20000 | Transacciones que se toman de fraudTest |
| `HIST_FRAUDTEST_FRAUDE_PCT` | 3 | Porcentaje de ellas que son fraude |
| `HIST_RAW_DIR` | se busca en `db/datasets/raw/` y luego en `data/kaggle/` | Carpeta de los CSV |

`SEED_RESET=true` en el seed vacía también `transacciones`: después de
resembrar hay que volver a correr el ETL. Las pruebas del ETL (no usan la
base de datos ni los CSV reales) se corren con:

``` bash
uv run pytest db/datasets
```

#### Errores frecuentes del ETL

| Mensaje | Causa y solución |
|---|---|
| `Faltan estos archivos en ...` | Los dos CSV no están juntos en una de las carpetas que lista el mensaje. Ver "Dónde guardar los CSV". |
| `El SHA-256 de ... no coincide con el del equipo` | Tienes otra versión del archivo, u otro dataset con ese nombre. Descárgalo de nuevo. `--omitir-hash` lo salta, pero los datos ya no serán iguales a los del equipo. |
| `El seed no ha creado usuarios con dispositivo...` | Falta el paso 7 (o la base apunta a otro lugar: revisa `DATABASE_URL`). |
| `Connection refused` / `could not connect` | PostgreSQL apagado o puerto equivocado en `DATABASE_URL`: 5432 si está instalado, 5433 si es el de Compose. |
| La huella es distinta a la de tus compañeros | Ver "Comprobar que todos obtienen los mismos datos" (arriba). |

### Paso 8c --- Cargar PaySim y fraudTest al Data Lake (S3)

Descarga los dos datasets de Kaggle, los valida y los deja **tal cual
llegaron** (sin transformar) en la capa cruda del Data Lake, para que
después los procese Spark. El motor no los consume. No usa PostgreSQL ni
toca ninguna tabla.

**Antes de empezar:** LocalStack levantado (paso 5, el bucket
`pagoseguro-datalake` ya existe) y el `.env` creado (paso 6).

#### Requisitos y configuración

-   Python 3.12, `uv` y Docker Desktop (para LocalStack).
-   Un token de Kaggle: [kaggle.com/settings/api](https://www.kaggle.com/settings/api)
    → *Generate New Token*. Va **solo en tu `.env`**, nunca en el repo ni en
    la consola compartida. En `.env.example` la variable está vacía.

``` env
KAGGLE_API_TOKEN=tu_token
KAGGLE_DOWNLOAD_DIR=data/kaggle
# KAGGLE_FORCE_DOWNLOAD=true   # vuelve a descargar aunque el CSV ya exista
DATALAKE_BUCKET=pagoseguro-datalake
```

`data/kaggle/` está en el `.gitignore`: los CSV nunca van a Git.

#### Dónde van los CSV

Si ya tienes los archivos, no hace falta token: coloca los archivos que requiere este flujo en
`data/kaggle/` y el comando no vuelve a descargarlos. Este flujo es independiente del ETL de PostgreSQL del paso 8b.

``` text
data/kaggle/PS_20174392719_1491204439457_log.csv   # ealaxi/paysim1
data/kaggle/fraudTest.csv                          # kartik2112/fraud-detection
```

#### Ejecutar

``` bash
uv run python -m sources.csv_files.kaggle
```

Para cada dataset: descarga (si falta), valida existencia, encabezado exacto
(columnas y orden) y número de filas, calcula el SHA-256, sube el CSV y,
**solo cuando terminó bien**, escribe el manifiesto. Si algo no coincide con
el contrato no sube nada de ese dataset y el comando termina con código 1
(el otro dataset se procesa igual).

| Dataset | Archivo | Filas (sin encabezado) | Columnas |
|---|---|---|---|
| `ealaxi/paysim1` | `PS_20174392719_1491204439457_log.csv` | 6.362.620 | 11: `step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig, nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud` |
| `kartik2112/fraud-detection` | `fraudTest.csv` | 555.719 | 23: `(sin nombre), trans_date_trans_time, cc_num, merchant, category, amt, … , merch_long, is_fraud` |

Los valores del contrato están en `sources/csv_files/kaggle/config.py`. Si un
archivo real no los cumple, **no los cambies en el código**: avisa a Jorge.

#### Rutas en S3

| Objeto | Ruta |
|---|---|
| PaySim | `s3://pagoseguro-datalake/raw/kaggle/paysim/paysim.csv` |
| Manifiesto de PaySim | `s3://pagoseguro-datalake/raw/kaggle/paysim/_manifest.json` |
| fraudTest | `s3://pagoseguro-datalake/raw/kaggle/sparkov/fraudtest/fraudTest.csv` |
| Manifiesto de fraudTest | `s3://pagoseguro-datalake/raw/kaggle/sparkov/fraudtest/_manifest.json` |

Las rutas no llevan fecha: es un histórico, y volver a correr el comando
sobrescribe el mismo archivo en vez de crear copias. El manifiesto es la
señal de "carga completa" y trae `dataset`, `archivo_original`, `filas`,
`columnas`, `sha256`, `bytes` y `cargado_en` (UTC).

#### Verificar los objetos

Deben verse 4 objetos:

``` bash
uv run python -c "from shared.aws import cliente; [print(o['Key'], o['Size']) for o in cliente('s3').list_objects_v2(Bucket='pagoseguro-datalake', Prefix='raw/kaggle/')['Contents']]"
```

#### Comprobar la idempotencia

Corre el comando dos veces. La segunda debe mostrar `ya cargado` en los dos
datasets y no subir nada (compara el SHA-256 del archivo local con el del
manifiesto y comprueba que el CSV siga en S3 con el mismo tamaño):

``` bash
uv run python -m sources.csv_files.kaggle   # subido
uv run python -m sources.csv_files.kaggle   # ya cargado
```

#### Pruebas

No descargan de Kaggle ni usan internet: crean CSV pequeños en directorios
temporales. La prueba contra S3 se salta sola si LocalStack no está levantado.

``` bash
uv run pytest sources/csv_files/kaggle
```

#### Advertencias de tamaño

-   PaySim pesa ~470 MB y tiene 6,3 millones de filas; fraudTest, ~150 MB. Si
    el CSV no está en `data/kaggle/`, la descarga de `kartik2112/fraud-detection`
    trae también `fraudTrain.csv`, que no se valida ni se sube.
    La descarga depende de tu conexión.
-   El archivo se lee **por bloques y por líneas**, nunca entero en memoria
    (no se usa pandas), pero se recorre dos veces (hash y conteo): espera
    del orden de decenas de segundos por dataset en un computador normal,
    más el tiempo de subida.
-   Necesitas ~650 MB libres en `data/kaggle/`.

#### Errores frecuentes

| Mensaje | Causa y solución |
|---|---|
| `Falta KAGGLE_API_TOKEN en el .env` | Falta el token y el CSV no está en `data/kaggle/`. Ponlo en tu `.env` o copia el CSV a mano. |
| `tiene N filas y se esperaban M` / `el encabezado ... no coincide` | El archivo no es el del contrato (versión distinta u otro dataset, p. ej. `creditcard.csv` con columnas `V1` … `V28` en vez de `fraudTest.csv`). No se sube nada; avisa a Jorge. |
| `no existe el archivo` | El CSV no está en `KAGGLE_DOWNLOAD_DIR` con el nombre exacto. |
| `NoSuchBucket` / `Could not connect to the endpoint URL` | LocalStack apagado o sin el bucket: `docker compose up -d` y `docker compose ps` (debe estar `healthy`). |
| `Read timeout` en la subida | Conexión lenta con un archivo grande; repite el comando (la carga no deja manifiesto de éxito si falló). |

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

Las pruebas de `sources/csv_files/kaggle` no necesitan servicios; solo la de
integración con S3 usa LocalStack y se omite si no está levantado
(`uv run pytest sources/csv_files/kaggle`). Las del ETL
(`uv run pytest db/datasets`) y las de las tasas de cambio
(`uv run pytest sources/apis/exchange_rates`) tampoco necesitan servicios,
internet ni los CSV reales.

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

### Paso 15 --- Consultar las tasas de cambio (API Frankfurter)

Pide a [Frankfurter](https://frankfurter.dev) (API pública de tasas de
cambio, sin cuenta ni token) cuántos COP, EUR y JPY vale 1 USD, valida la
respuesta y guarda el resultado como evidencia del consumo de la API. En AWS
esta tarea corre como Lambda; en local escribe un archivo.

``` bash
uv run python -m sources.apis.exchange_rates
```

Muestra la fecha de las tasas y `1 USD = ... COP/EUR/JPY` (los mensajes del
programa están en inglés) y guarda
`sources/apis/exchange_rates/data/rates_AAAA-MM-DD.json`; Git ignora esa
carpeta.

-   **Necesita internet:** llama a la API real. Reintenta hasta 3 veces ante
    errores del servidor o de red.
-   **No guarda datos a medias:** si la respuesta viene incompleta o con tasas
    inválidas, falla y no escribe nada.
-   **Las tasas se guardan como texto**, no como número decimal, para no
    perder precisión.
-   **No lo usa el generador de transacciones:** ese lee las tasas fijas de
    `generators/data/tasas_2026-10-01.json`, para que todas las corridas den
    lo mismo sin internet. Ese archivo se regenera con
    `uv run python -m generators.fetch_rates`.

### Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `Connection refused` a `localhost:5432` o `5433` | PostgreSQL apagado, o el puerto de `DATABASE_URL` no es el de tu opción: 5432 si lo instalaste (opción A), 5433 si es el de Compose (opción B). |
| `Falta LOCALSTACK_AUTH_TOKEN en el .env` al hacer `docker compose up` | Pega tu token de LocalStack en el `.env` (paso 5). |
| `POST /transactions` responde 503 | Valkey apagado: `docker compose up -d valkey` (paso 5). |
| `Could not connect to the endpoint URL` | LocalStack apagado: `docker compose up -d localstack` y `docker compose ps` (debe quedar `healthy`). |
| El ETL o los extractos no encuentran datos | Falta correr el seed (paso 7) o el generador (paso 9). |
| Aparecen columnas `V1`, `V2`... en un dataset | Es `creditcard.csv`, que el proyecto no usa. Usa `fraudTest.csv` (ver "Datasets históricos"). |

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
