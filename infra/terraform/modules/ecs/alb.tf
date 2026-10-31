# Public load balancer in the two public subnets. It terminates TLS on 443
# and forwards plain HTTP to the engine port of a task in app-a or app-b.

# Without a domain (dev), Terraform makes a self-signed certificate and
# imports it into ACM, so the listener still speaks TLS; clients skip the
# check (curl -k). With a domain, ACM issues a public certificate validated
# by DNS: the validation record is an output to add at the DNS provider.

resource "tls_private_key" "self_signed" {
  count = var.domain_name == null ? 1 : 0

  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "self_signed" {
  count = var.domain_name == null ? 1 : 0

  private_key_pem       = tls_private_key.self_signed[0].private_key_pem
  validity_period_hours = 24 * 30
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth"]

  subject {
    common_name  = "${var.name_prefix}.invalid"
    organization = "SecurePay"
  }
}

resource "aws_acm_certificate" "self_signed" {
  count = var.domain_name == null ? 1 : 0

  private_key      = tls_private_key.self_signed[0].private_key_pem
  certificate_body = tls_self_signed_cert.self_signed[0].cert_pem

  tags = { Name = "${var.name_prefix}-alb-self-signed" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate" "domain" {
  count = var.domain_name == null ? 0 : 1

  domain_name       = var.domain_name
  validation_method = "DNS"

  tags = { Name = "${var.name_prefix}-alb" }

  lifecycle {
    create_before_destroy = true
  }
}

# Waits until the DNS record of the domain certificate exists and ACM has
# issued it (up to 75 minutes by default).
resource "aws_acm_certificate_validation" "domain" {
  count = var.domain_name == null ? 0 : 1

  certificate_arn = aws_acm_certificate.domain[0].arn
}

locals {
  certificate_arn = var.domain_name == null ? aws_acm_certificate.self_signed[0].arn : aws_acm_certificate_validation.domain[0].certificate_arn
}

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.alb_security_group_id]

  drop_invalid_header_fields = true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "engine" {
  name        = "${var.name_prefix}-engine"
  vpc_id      = var.vpc_id
  target_type = "ip" # Fargate tasks have their own network interface
  protocol    = "HTTP"
  port        = var.engine_port

  # A task being replaced gets 30 s to finish its requests.
  deregistration_delay = 30

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.engine.arn
  }
}
