"""Architecture flow on AWS: doc-website/static/img/architecture-flow.jpg.

Drawn from what Terraform creates (infra/terraform/modules, envs/dev). The
labels are in Spanish, like the first version of the diagram (the pages say
so under the image). The picture has a data band in the middle (DynamoDB,
Valkey, RDS, the SNS topic of the e-mails and the Data Lake) and the zones
that use it above (what happens per transaction) and below (what runs on a
schedule, the APIs, the night and the dashboard), plus the order of the one
`terraform apply` at the bottom. Run from the repository root:

    python3 doc-website/diagrams/architecture_flow.py

(Node's Playwright with Chromium draws the image). Change it when a
service, a flow or the monthly cost changes.
"""

from __future__ import annotations

from pathlib import Path

from common import FLOW, MUTED, Card, Svg, legend, panel, render

W, H = 2600, 1372
CW, CH = 270, 62


def zone(s: Svg, x, y, w, h, title, flow, bottom=False):
    """A white area with a colored bar; the title goes at the bottom when
    arrows come in from above."""
    s.box(x, y, w, h, fill="#ffffff", stroke="#cdd6e3", rx=12)
    bar = y + h - 6 if bottom else y
    s.add(f'<rect x="{x}" y="{bar}" width="{w}" height="6" rx="3" fill="{FLOW[flow]}"/>')
    s.text(x + 16, y + h - 16 if bottom else y + 30, title, size=14, weight="bold", color=FLOW[flow])


def card(x, y, title, sub, flow, icon, tag, w=CW, h=CH, **kw) -> Card:
    return Card(x, y, title, sub, flow, icon, tag, w=w, h=h, **kw)


s = Svg(W, H)
s.text(40, 44, "PagoSeguro Antifraude · arquitectura en AWS y cómo se comunica", size=24, weight="bold")
s.text(40, 68, "Lo que crea Terraform (noviembre de 2026). Arriba: lo que pasa con cada transacción · en el centro: dónde viven los datos · abajo: lo programado, las APIs, la noche y el tablero", size=13, color=MUTED)
s.box(W - 330, 26, 290, 30, fill="#e3eaf5", stroke="#cdd6e3", rx=15)
s.text(W - 185, 46, "us-east-2 (Ohio) · 2 zonas de disponibilidad", size=12, weight="bold", anchor="middle")

# ---- Top band: per transaction --------------------------------------------
TOP, R1, R2 = 86, 140, 260
zone(s, 30, TOP, 620, 254, "1 · Decisión en tiempo real (≤ 200 ms)", "realtime")
zone(s, 670, TOP, 970, 254, "2 · Después de responder (asíncrono)", "async")
zone(s, 1660, TOP, 910, 254, "Avisos y operación", "admin")

core = card(50, R1, "Core de la billetera", "Lo simula securepay-generator\n50 tx/s · pico de 300", "realtime", "external", "TX")
alb = card(50, R2, "Application Load Balancer", "HTTPS 443 · reparte en 2 zonas", "realtime", "network", "ALB")
engine = card(360, R2, "Fargate · motor (ECS)", "2 a 4 tareas en dev (4 a 24 en carga)\nSi tarda, decide según el monto", "realtime", "compute", "ECS")

sns_dec = card(690, R1, "SNS · decisiones", "Copia cada decisión a 3 colas", "async", "integration", "SNS")
sqs = card(1000, R1, "SQS · 3 colas + 3 DLQ", "casos · historial · analítica\n5 intentos, luego a la DLQ", "async", "integration", "SQS")
consumers = card(1310, R1, "Lambda ×3 · consumidores", "casos y reportes de lista · historial\n30 días · analítica (lotes de 1.000)", "async", "compute", "λ", w=310)

cw = card(1680, R1, "CloudWatch", "Logs, dashboard, filtros y alarmas", "admin", "management", "CW")
sns_ops = card(1980, R1, "SNS · ops-alarms", "Alarmas al equipo", "admin", "integration", "SNS")
mails = card(2280, R1, "Correos", "Equipo · supervisor\ncumplimiento · tesorería", "admin", "external", "@", h=182)
deploy = card(1680, R2, "GitHub Actions + ECR", "En cada merge: imagen por commit,\nactualiza el motor y las Lambdas", "admin", "management", "GH")

# ---- Data band --------------------------------------------------------------
zone(s, 30, 372, 2540, 150, "Datos y mensajería", "admin")
DY = 430
ddb = card(50, DY, "DynamoDB · tasas", "Tasas de cambio por día", "batch", "database", "DDB")
valkey = card(360, DY, "ElastiCache (Valkey)", "Idempotencia, historial, catálogo,\ncuentas, comercios y lista", "realtime", "database", "VK")
rds = card(670, DY, "RDS PostgreSQL 16 · Multi-AZ", "Usuarios, cuentas, comercios, lista restrictiva, reglas y sus versiones,\ncasos y reportes, historial de 30 días, conciliación · un usuario por componente", "admin", "database", "RDS", w=1030)
sns_biz = card(1740, DY, "SNS · business-alerts", "Un correo por audiencia (filtro)", "async", "integration", "SNS")
lake = card(2050, DY, "S3 · Data Lake", "raw/ (decisiones, extractos, Kaggle, export)\ncurated/ · analytics/ (Parquet) · athena-results/", "batch", "storage", "S3", w=510)

# ---- Bottom band --------------------------------------------------------------
BOT, B1, B2, B3 = 556, 612, 724, 836
zone(s, 30, BOT, 620, 384, "3 · Cargas diarias (EventBridge)", "batch", bottom=True)
zone(s, 670, BOT, 620, 384, "4 · Reglas, casos y evidencia", "admin", bottom=True)
zone(s, 1310, BOT, 410, 384, "5 · Cada noche (EventBridge 02:00)", "batch", bottom=True)
zone(s, 1740, BOT, 290, 384, "Alertas", "batch", bottom=True)
zone(s, 2050, BOT, 520, 384, "6 · Tablero y archivos de socios", "analytics", bottom=True)

rates_fn = card(50, B1, "Lambda · tasas de cambio", "11:00 Bogotá (imagen de securepay-apis)", "batch", "compute", "λ")
frank = card(50, B3, "API de Frankfurter", "Tasas públicas · 4 monedas", "batch", "external", "FX")
loader = card(360, B1, "Lambda · list-loader", "01:00 Bogotá: cuentas, comercios\ny lista restrictiva", "batch", "compute", "λ")

apis = card(690, B1, "Lambda · API de reglas y de casos", "Versiona reglas, simula, asigna y resuelve\ncasos, conciliación para tesorería", "admin", "compute", "λ", w=340)
evidence = card(1050, B1, "S3 · evidencia", "Object Lock 10 años\n(COMPLIANCE), al resolver", "admin", "storage", "S3", w=220)
gw = card(690, B2, "API Gateway + Cognito", "Token JWT · grupos analista y gerente\nsolo gerente cambia reglas (403)", "admin", "integration", "API", w=340)
people = card(690, B3, "Analistas, gerente y tesorería", "Páginas /rules-api y /cases-api", "admin", "external", "👤", w=340)

sfn = card(1330, B1, "Step Functions · la noche", "Orquesta los pasos en orden;\nsi falla la conciliación, alarma", "batch", "integration", "SF", w=370)
SW = 180
step = [
    card(1330, B2, "1 · Lambda", "lee los extractos", "batch", "compute", "λ", w=SW, h=50),
    card(1520, B2, "2 · Glue (Spark)", "cruce con decisiones", "batch", "analytics", "GL", w=SW, h=50),
    card(1330, B2 + 62, "3 · Lambda", "diferencias → RDS", "batch", "compute", "λ", w=SW, h=50),
    card(1520, B2 + 62, "4 · Lambda", "export y Kaggle", "batch", "compute", "λ", w=SW, h=50),
    card(1330, B2 + 124, "5 · Glue (Spark)", "modelo dimensional", "batch", "analytics", "GL", w=SW, h=50),
    card(1520, B2 + 124, "6 · Athena", "vistas q1 a q6", "batch", "analytics", "ATH", w=SW, h=50),
]

alerts = card(1752, B1, "Lambda · alertas", "Cada 5 min: escala casos de 4 h,\ncumplimiento, purga · 06:30 chequeo", "batch", "compute", "λ", w=268)

catalog = card(2070, B1, "Glue Data Catalog", "13 tablas · por fecha", "analytics", "analytics", "GL", w=230)
athena = card(2070, B2, "Athena · powerbi", "Vistas q1 a q6", "analytics", "analytics", "ATH", w=230)
pbi = card(2070, B3, "Power BI Desktop", "6 páginas · ODBC", "analytics", "external", "BI", w=230)
partners = card(2320, B1, "Socios (4)", "Dejan su extracto diario\nen raw/extractos/", "batch", "external", "TXT", w=230)

cards = [core, alb, engine, sns_dec, sqs, consumers, cw, sns_ops, mails, deploy, ddb, valkey, rds, sns_biz,
         lake, rates_fn, frank, loader, apis, evidence, gw, people, sfn, *step, alerts, catalog, athena,
         pbi, partners]

# ---- Arrows -------------------------------------------------------------------
# Real time.
s.arrow([core.bottom(), alb.top()], "realtime", "HTTPS")
s.arrow([alb.right(), engine.left()], "realtime")
s.arrow([engine.bottom(-60), valkey.top(-60)], "realtime", "4 viajes", both=True, lx=0)
s.arrow([ddb.top(110), (ddb.x + 250, alb.y + alb.h + 30), (engine.x - 18, alb.y + alb.h + 30), (engine.x - 18, engine.cy + 16), engine.left(16)], "realtime", "tasa del día", at=1, dashed=True, ly=-12)

# Asynchronous.
s.arrow([engine.top(), (engine.cx, sns_dec.cy), sns_dec.left()], "async", "publica la decisión", at=1, lx=-20, ly=-12)
s.arrow([sns_dec.right(), sqs.left()], "async")
s.arrow([sqs.right(), consumers.left()], "async")
s.arrow([consumers.bottom(-60), (consumers.cx - 60, rds.y)], "async", "casos e historial", ly=-6)
s.arrow([consumers.right(14), (1650, consumers.cy + 14), (1650, 352), (lake.x + 440, 352), lake.top(185)], "async", "raw/decisiones", at=2, lx=-200)

# Notices.
s.arrow([cw.right(), sns_ops.left()], "admin")
s.arrow([sns_ops.right(), (mails.x, sns_ops.cy)], "admin")
s.arrow([sns_biz.top(), (sns_biz.cx, 362), (mails.cx - 60, 362), mails.bottom(-60)], "async", "por audiencia", at=1, lx=60)

# Daily loads.
s.arrow([frank.top(), rates_fn.bottom()], "batch", "trae las tasas")
s.arrow([rates_fn.top(), ddb.bottom()], "batch")
s.arrow([loader.top(-40), valkey.bottom(-40)], "batch", "reemplaza")
s.arrow([rds.left(16), (652, rds.cy + 16), (652, loader.cy), loader.right()], "batch", "lee", at=1, lx=-22, ly=70)

# Rules, cases and evidence.
s.arrow([people.top(), gw.bottom()], "admin", "HTTPS")
s.arrow([gw.top(), apis.bottom()], "admin", "X-User = correo")
s.arrow([apis.top(80), (apis.cx + 80, rds.y + rds.h)], "admin", "lee y escribe", both=True, ly=4)
s.arrow([apis.left(-14), (672, apis.cy - 14), (672, 540), (valkey.x + 230, 540), valkey.bottom(95)], "admin", "publica el catálogo", at=2, ly=14)
s.arrow([apis.right(), evidence.left()], "admin")

# The night.
s.arrow([sfn.top(-100), (sfn.cx - 100, rds.y + rds.h)], "batch", "pasos 3 y 4", ly=4)
s.arrow([sfn.bottom(), (sfn.cx, step[0].y - 6)], "batch", start_dot=False)
s.arrow([sfn.right(-14), (1728, sfn.cy - 14), (1728, 538), (lake.x + 40, 538), lake.bottom(-215)], "batch", "lee y escribe el lago", at=2, ly=-12)
s.arrow([sfn.top(130), (sfn.cx + 130, 548), (sns_biz.cx - 60, 548), sns_biz.bottom(-60)], "batch", "tesorería", at=1, lx=0, ly=10)

# Alerts.
s.arrow([alerts.top(40), sns_biz.bottom(40)], "batch", "supervisor y cumplimiento", ly=-30)
s.arrow([alerts.top(-90), (alerts.cx - 90, 520), (rds.x + rds.w - 20, 520), rds.bottom(rds.w / 2 - 20)], "batch")

# Dashboard and partners.
s.arrow([lake.bottom(-140), catalog.top()], "analytics", "analytics/")
s.arrow([catalog.bottom(), athena.top()], "analytics")
s.arrow([athena.bottom(), pbi.top()], "analytics", "al tablero")
s.arrow([partners.top(), (partners.cx, lake.y + lake.h)], "batch", "suben el archivo")

for c in cards:
    s.card(c)

# ---- The one apply --------------------------------------------------------------
AY = 962
zone(s, 30, AY, 2540, 130, "7 · Montaje de dev: un terraform apply, en este orden (desde el contenedor deployer)", "admin")
seq = [
    ("TF", "management", "Terraform", "Red, seguridad, datos,\nservicios y alarmas"),
    ("ECR", "compute", "Imágenes a ECR", "Motor, seed y APIs,\ntag = commit"),
    ("λ", "compute", "Lambda · db-bootstrap", "Tablas, usuarios y permisos\n(única con la clave maestra)"),
    ("ECS", "compute", "Fargate · tarea admin", "Seed de la BD y ETL de\nKaggle (imagen del seed)"),
    ("λ", "compute", "Invoca list-loader y tasas", "Valkey y DynamoDB listos\npara el motor"),
    ("S3", "storage", "Sube el día de demo", "Extractos, decisiones y\nKaggle; arranca la noche"),
]
sw, gx = 390, 32
prev = None
for i, (tag, icon, title, sub) in enumerate(seq):
    c = card(50 + i * (sw + gx), AY + 50, f"{i + 1} · {title}", sub, "admin", icon, tag, w=sw)
    if prev:
        s.arrow([prev.right(), c.left()], "admin", start_dot=False)
    s.card(c)
    prev = c

# ---- Panels -------------------------------------------------------------------
py = 1118
panel(s, 40, py, 600, 236, "Red y seguridad", [
    ("network", "VPC", "VPC · 2 zonas · subredes pública, app y datos", "NAT ×2; endpoints de S3 y DynamoDB"),
    ("security", "SG", "Grupos de seguridad por componente", "El motor no llega a RDS; caché por red y TLS"),
    ("security", "IAM", "IAM: un rol por componente", "Deploy por OIDC, sin llaves en GitHub"),
    ("security", "SSM", "Claves en Parameter Store", "Una por usuario de BD; datos cifrados en reposo"),
])
panel(s, 660, py, 600, 236, "Lambdas (12)", [
    ("compute", "λ", "Consumidores: casos, historial, analítica", "Leen las 3 colas SQS"),
    ("compute", "λ", "Programadas: alertas, list-loader, tasas", "EventBridge Scheduler"),
    ("compute", "λ", "Noche: statement-reader, difference-writer,", "analytics-export (Step Functions)"),
    ("compute", "λ", "APIs: rules-api, cases-api · db-bootstrap", "API Gateway · invocada por Terraform"),
])
panel(s, 1280, py, 600, 236, "Pruebas y costo", [
    ("compute", "EC2", "EC2 · Locust dentro de la VPC (opcional)", "Carga a 50, 150 y 300 tx/s"),
    ("management", "K8S", "kind y EKS solo para comparar (ADR-06)", "La plataforma es ECS"),
    ("management", "$", "AWS Budgets", "Alerta de gasto (USD 5 en dev)"),
    ("database", "≈", "≈ $346/mes en producción", "≈ $17/mes en desarrollo"),
])
legend(s, 1900, py, 660, 236, [
    ("realtime", "Decisión en tiempo real (≤ 200 ms)", False),
    ("async", "Asíncrono, después de responder", False),
    ("batch", "Programado: cargas diarias, alertas y la noche", False),
    ("analytics", "Analítica y tablero", False),
    ("admin", "Gestión, avisos y montaje", False),
    ("realtime", "Punteada: el motor tiene las tasas en memoria", True),
    ("admin", "El punto marca dónde nace la flecha", False),
], "≈ Los horarios son de Bogotá; EventBridge Scheduler los dispara")

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "static" / "img" / "architecture-flow.jpg"
    render(s.svg(), out)
    print(out)
