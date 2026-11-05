# The load test's client inside the VPC (HU-60, topic 6 of the brief: EC2).
# From a laptop in Colombia every request carried 80 to 120 ms of internet
# and one computer's CPU; from here Locust is a few milliseconds from the
# load balancer, so its own numbers can be compared with the 200 ms.
#
# No SSH, no key pair and no inbound rule: AWS Systems Manager runs the
# test (aws ssm send-command, the output load_test_command) and the
# results go to S3. Everything here exists only with enabled = true, so the
# role lives with the machine and not in modules/iam.

locals {
  p = var.name_prefix
}

data "aws_ssm_parameter" "al2023" {
  count = var.enabled ? 1 : 0

  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_iam_role" "this" {
  count = var.enabled ? 1 : 0

  name = "${local.p}-load-runner"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

# Systems Manager's agent (preinstalled on Amazon Linux 2023): send-command
# and Session Manager without SSH.
resource "aws_iam_role_policy_attachment" "ssm" {
  count = var.enabled ? 1 : 0

  role       = aws_iam_role.this[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "results" {
  count = var.enabled ? 1 : 0

  name = "${local.p}-load-runner"
  role = aws_iam_role.this[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "WriteLoadTestResults"
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "arn:aws:s3:::${var.results_bucket}/load-tests/*"
    }]
  })
}

resource "aws_iam_instance_profile" "this" {
  count = var.enabled ? 1 : 0

  name = "${local.p}-load-runner"
  role = aws_iam_role.this[0].name
}

# Out on 443 only: GitHub, uv's downloads, Systems Manager, S3 and the
# load balancer. Nothing comes in.
resource "aws_security_group" "this" {
  count = var.enabled ? 1 : 0

  name        = "${local.p}-sg-load-runner"
  description = "Load test client (EC2): HTTPS out only"
  vpc_id      = var.vpc_id

  tags = { Name = "${local.p}-sg-load-runner" }
}

resource "aws_vpc_security_group_egress_rule" "https" {
  count = var.enabled ? 1 : 0

  security_group_id = aws_security_group.this[0].id
  description       = "HTTPS out"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "this" {
  count = var.enabled ? 1 : 0

  ami                    = data.aws_ssm_parameter.al2023[0].value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this[0].id]
  iam_instance_profile   = aws_iam_instance_profile.this[0].name

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repository = var.repository
    git_ref    = var.git_ref
    host       = var.target_host
    bucket     = var.results_bucket
  })
  user_data_replace_on_change = true

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 16
    encrypted   = true
  }

  tags = { Name = "${local.p}-load-runner" }
}
