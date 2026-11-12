"""The AWS network of dev: doc-website/static/img/network-diagram.png.

Every box is something Terraform creates in infra/terraform/envs/dev. Run
from the repository root (needs Node's Playwright and its Chromium):

    python3 doc-website/diagrams/network.py

Change it when a subnet, a security group, a route or a service changes.
"""

from __future__ import annotations

from pathlib import Path

from common import Card, Svg, legend, panel, render

W, H = 1300, 2090
s = Svg(W, H)


def group(x, y, w, h, name, color="#c9384a", dashed=True):
    s.box(x, y, w, h, fill="none", stroke=color, rx=8, dash=dashed, width=1.4)
    s.text(x + 10, y + 16, name, size=11.5, weight="bold", color=color)


def area(x, y, w, h, name, sub, fill, stroke):
    s.box(x, y, w, h, fill=fill, stroke=stroke, rx=8)
    s.text(x + 10, y + 17, name, size=11.5, weight="bold", color=stroke)
    if sub:
        s.text(x + 10, y + 31, sub, size=10.5, color=stroke)


s.text(30, 44, "SecurePay · AWS network", size=24, weight="bold")
s.text(30, 68, "What Terraform creates in infra/terraform/envs/dev · names are securepay-dev-<name> · the color of each arrow is the kind of traffic", size=12.5, color="#5b6676")
s.box(W - 300, 28, 270, 30, fill="#e3eaf5", stroke="#cdd6e3", rx=15)
s.text(W - 165, 48, "Region us-east-2 (Ohio) · 2 zones", size=12, weight="bold", anchor="middle")

# Containers.
s.box(20, 190, 1260, 1570, fill="#eef2f8", stroke="#7d9cc4", rx=10, dash=True)
s.text(32, 208, "AWS Cloud · Region us-east-2", size=11.5, weight="bold", color="#2f5f9a")
s.box(40, 225, 1220, 1085, fill="#eaf0f8", stroke="#2b3a55", rx=10, width=1.8)
s.text(54, 245, "VPC securepay-dev-vpc · 10.0.0.0/16", size=12, weight="bold", color="#2b3a55")

zones = {"a": 70, "b": 670}
for z, zx in zones.items():
    s.box(zx, 470, 560, 625, fill="none", stroke="#8a94a6", rx=8, dash=True)
    s.text(zx + 10, 486, f"us-east-2{z}", size=11.5, weight="bold", color="#5b6676")
    i = 0 if z == "a" else 1
    area(zx + 12, 496, 536, 112, f"public-{z}", f"10.0.{i}.0/24", "#edf7f0", "#3f8a5a")
    area(zx + 12, 620, 536, 292, f"app-{z} · private", f"10.0.1{i}.0/24", "#eaf1fb", "#3a6fb0")
    area(zx + 12, 925, 536, 155, f"data-{z} · private", f"10.0.2{i}.0/24", "#f2eefa", "#6b4fa8")

C = Card
internet = C(500, 108, "Internet", "Wallet core, analysts' browsers, Power BI", "realtime", "external", "WWW", w=300, h=58)
igw = C(500, 262, "Internet Gateway", "securepay-dev-igw · target of rt-public", "admin", "network", "IGW", w=300, h=58)
alb = C(500, 372, "Application Load Balancer", "443, ACM certificate · public-a and b", "realtime", "network", "ALB", w=300, h=60)
nat_a = C(110, 538, "NAT Gateway a", "securepay-dev-nat-a + Elastic IP\nExit for app-a", "async", "network", "NAT", w=250, h=62)
nat_b = C(950, 538, "NAT Gateway b", "securepay-dev-nat-b + Elastic IP\nExit for app-b", "async", "network", "NAT", w=250, h=62)
lam_a = C(110, 686, "Lambdas in the VPC", "9 of the 12 · one IAM role each\nconsumers, APIs, alerts", "batch", "compute", "λ", w=225, h=62)
eng_a = C(375, 686, "Engine (Fargate)", "Tasks in app-a · port 8000\nIAM role: engine", "realtime", "compute", "ECS", w=220, h=62)
adm_a = C(110, 806, "Admin task (Fargate)", "Seed and Kaggle ETL\nOn demand · IAM role: admin", "batch", "compute", "ECS", w=225, h=62)
ec2_a = C(375, 806, "Load runner (EC2)", "Locust · c7i-flex.large\nOptional · no SSH", "admin", "compute", "EC2", w=220, h=62, dashed=True)
eng_b = C(700, 686, "Engine (Fargate)", "Tasks in app-b · port 8000\nIAM role: engine", "realtime", "compute", "ECS", w=220, h=62)
lam_b = C(965, 686, "Lambdas in the VPC", "Same functions, zone b", "batch", "compute", "λ", w=225, h=62)
rds_a = C(110, 991, "RDS PostgreSQL 16", "Primary · db.t3.micro · one endpoint\nEncrypted, TLS only", "batch", "database", "RDS", w=260, h=62)
rds_b = C(955, 991, "RDS standby (Multi-AZ)", "Gets no connections: only copies\nTakes over if zone a fails", "replication", "database", "RDS", w=240, h=62)
cache = C(470, 1142, "ElastiCache Serverless for Valkey", "One for the VPC · 6379/6380 · TLS · no users\nInterfaces in data-a and data-b", "realtime", "database", "VK", w=360, h=62)
endp = C(880, 1240, "Gateway endpoints", "S3 and DynamoDB, on the VPC edge\nIn the route tables of app and data", "analytics", "network", "VPCE", w=300, h=58)

group(488, 348, 324, 96, "sg-alb")
group(100, 662, 245, 96, "sg-lambda")
group(365, 662, 240, 96, "sg-engine")
group(100, 782, 245, 96, "sg-admin")
group(365, 782, 240, 96, "sg-load-runner")
group(690, 662, 240, 96, "sg-engine")
group(955, 662, 245, 96, "sg-lambda")
group(100, 967, 280, 96, "sg-rds")
group(945, 967, 260, 96, "sg-rds")
group(458, 1118, 384, 96, "sg-cache")

# Arrows.
s.arrow([internet.bottom(), igw.top()], "realtime", "443")
s.arrow([igw.bottom(), alb.top()], "realtime", "443")
s.arrow([alb.left(), (eng_a.cx - 40, alb.cy), eng_a.top(-40)], "realtime", "8000", at=1, ly=10)
s.arrow([alb.right(), (eng_b.cx + 40, alb.cy), eng_b.top(40)], "realtime", "8000", at=1, ly=10)
s.arrow([eng_a.top(50), (eng_a.cx + 50, nat_a.cy - 10), nat_a.right(-10)], "async", "443 out", at=1)
s.arrow([lam_a.top(-10), nat_a.bottom(-20)], "async", "443 out")
s.arrow([ec2_a.right(), (618 - 4, ec2_a.cy), (614, nat_a.cy + 14), nat_a.right(14)], "async", at=1, start_dot=True)
s.arrow([eng_b.top(-50), (eng_b.cx - 50, nat_b.cy - 10), nat_b.left(-10)], "async", "443 out", at=1)
s.arrow([lam_b.top(), (lam_b.cx, nat_b.y + nat_b.h)], "async", "443 out")
s.arrow([nat_a.top(), (nat_a.cx, igw.cy), igw.left()], "async", at=1)
s.arrow([nat_b.top(), (nat_b.cx, igw.cy), igw.right()], "async", at=1)
s.arrow([lam_a.left(), (92, lam_a.cy), (92, rds_a.cy), rds_a.left()], "batch", "5432", at=1)
s.arrow([adm_a.bottom(), (adm_a.cx, rds_a.y)], "batch", "5432")
s.arrow([lam_b.bottom(60), (lam_b.cx + 60, 917), (rds_a.cx + 80, 917), rds_a.top(80)], "batch", "5432", at=1, lx=180)
s.arrow([eng_a.right(10), (645, eng_a.cy + 10), (645, cache.y)], "batch", "6379/6380", at=1, ly=150)
s.arrow([eng_b.bottom(), (eng_b.cx, cache.y)], "batch", "6379/6380", ly=150)
s.arrow([lam_b.left(18), (938, lam_b.cy + 18), (938, cache.cy + 16), cache.right(16)], "batch", "6379/6380", at=1, ly=170)
s.arrow([rds_a.right(), rds_b.left()], "replication", "sync replication", dashed=True, both=True, lx=-40, ly=-12)
s.arrow([(1230, 1000), (1245, 1000), (1245, endp.cy), endp.right()], "analytics", "route tables", at=1)
s.arrow([(52, 1060), (52, endp.cy), endp.left()], "analytics", start_dot=True)

for c in [internet, igw, alb, nat_a, nat_b, lam_a, eng_a, adm_a, ec2_a, eng_b, lam_b, rds_a, rds_b, cache, endp]:
    s.card(c)

# Services outside the VPC.
s.box(40, 1330, 1220, 410, fill="#f5f7fb", stroke="#b5c1d3", rx=10, dash=True)
s.text(54, 1350, "AWS services outside the VPC", size=12, weight="bold", color="#2b3a55")
s.text(54, 1366, "Regional services: reached over 443 through the NAT and the Internet Gateway, or through the gateway endpoints", size=10.5, color="#5b6676")
xs = [60, 360, 660, 960]
ys = [1420, 1525, 1630]
out = [
    ("API Gateway + Cognito", "HTTP API: rules and cases routes\nJWT of analista / gerente", "admin", "integration", "API"),
    ("SNS + SQS", "3 topics, 3 queues with DLQ\nAnalytics batches: 1,000 or 60 s", "async", "integration", "SQS"),
    ("Amazon DynamoDB", "Exchange rates table\nRead by the engine at startup", "analytics", "database", "DDB"),
    ("Amazon S3", "datalake, evidence (Object Lock),\nlist-provider, artifacts", "analytics", "storage", "S3"),
    ("Lambdas outside the VPC", "analytics-consumer, statement-reader,\nexchange-rates (Frankfurter)", "batch", "compute", "λ"),
    ("Step Functions + Scheduler", "Nightly reconciliation and analytics\n5 schedules", "batch", "integration", "SF"),
    ("Glue + Athena", "2 Spark jobs (role glue-jobs)\nWorkgroup powerbi, views q1-q6", "batch", "analytics", "GL"),
    ("Amazon ECR", "engine, admin, apis, generator\nPulled through the NAT", "admin", "compute", "ECR"),
    ("Systems Manager", "Parameter Store: 10 parameters\nSession Manager to the admin task", "admin", "management", "SSM"),
    ("CloudWatch", "Logs, dashboard, alarms\nAlarms to SNS ops-alarms", "admin", "management", "CW"),
    ("IAM + Budgets", "21 roles, GitHub OIDC, powerbi user\nUSD 5 monthly budget", "admin", "security", "IAM"),
]
cards = {}
for i, (t, sub, flow, icon, tag) in enumerate(out):
    c = C(xs[i % 4], ys[i // 4], t, sub, flow, icon, tag, w=270, h=66)
    cards[t] = c
    s.card(c)
ddb, s3 = cards["Amazon DynamoDB"], cards["Amazon S3"]
s.arrow([endp.bottom(-60), (endp.cx - 60, 1395), (ddb.cx, 1395), ddb.top()], "analytics", at=1, start_dot=False)
s.arrow([endp.bottom(60), (s3.cx, 1395), s3.top()], "analytics", start_dot=False)

# Panels.
py = 1790
panel(s, 20, py, 400, 286, "Route tables", [
    ("network", "RT", "rt-public", "0.0.0.0/0 → Internet Gateway"),
    ("network", "RT", "rt-app-a / rt-app-b", "0.0.0.0/0 → NAT of the same zone; S3, DynamoDB → endpoints"),
    ("network", "RT", "rt-data", "No default route: no internet; S3, DynamoDB → endpoints"),
    ("network", "ACL", "Network ACLs", "The default ones (allow all): the security groups filter"),
    ("security", "SG", "Rules point at groups, not at IPs", "Dashed red boxes are the security groups"),
])
panel(s, 435, py, 470, 286, "Security groups", [
    ("security", "SG", "sg-alb · sg-engine", "alb: in 443 from 0.0.0.0/0, out 8000 · engine: out 6379/6380, 443"),
    ("security", "SG", "sg-lambda · sg-admin", "lambda: out 5432, 6379/6380, 443 · admin: out 5432, 443"),
    ("security", "SG", "sg-rds", "in 5432 from sg-lambda and sg-admin · no outbound"),
    ("security", "SG", "sg-cache", "in 6379/6380 from sg-engine and sg-lambda · no outbound"),
    ("security", "SG", "sg-load-runner", "out 443 only (the ALB through the NAT)"),
])
legend(s, 920, py, 360, 286, [
    ("realtime", "Inbound from the internet (HTTPS)", False),
    ("async", "Outbound 443 through the NAT of the same zone", False),
    ("batch", "Inside the VPC, between security groups", False),
    ("analytics", "To S3 and DynamoDB through the endpoints", False),
    ("replication", "Replication", True),
    ("admin", "Dashed card: optional (load_runner)", True),
    ("admin", "The dot marks where the connection starts", False),
], "Dev ≈ USD 0.15 an hour · destroy after each session")

if __name__ == "__main__":
    out_path = Path(__file__).resolve().parents[1] / "static" / "img" / "network-diagram.png"
    render(s.svg(), out_path)
    print(out_path)
