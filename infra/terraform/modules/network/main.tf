# VPC with three tiers in two zones (doc-website/docs/architecture/security.mdx#network).

data "aws_region" "current" {}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id            = aws_vpc.this.id
  cidr_block        = var.public_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  # The load balancer and the NAT Gateways get their public addresses
  # explicitly; nothing else is launched here.
  map_public_ip_on_launch = false

  tags = { Name = "${var.name_prefix}-public-${var.zone_suffixes[count.index]}", tier = "public" }
}

resource "aws_subnet" "app" {
  count = 2

  vpc_id            = aws_vpc.this.id
  cidr_block        = var.app_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${var.name_prefix}-app-${var.zone_suffixes[count.index]}", tier = "app" }
}

resource "aws_subnet" "data" {
  count = 2

  vpc_id            = aws_vpc.this.id
  cidr_block        = var.data_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${var.name_prefix}-data-${var.zone_suffixes[count.index]}", tier = "data" }
}

# One NAT per zone (ADR-08): losing a zone does not cut the other zone's egress.
resource "aws_eip" "nat" {
  count = 2

  domain = "vpc"

  tags = { Name = "${var.name_prefix}-nat-${var.zone_suffixes[count.index]}" }
}

resource "aws_nat_gateway" "this" {
  count = 2

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = { Name = "${var.name_prefix}-nat-${var.zone_suffixes[count.index]}" }

  depends_on = [aws_internet_gateway.this]
}

# Route tables: 1 public, 2 application (one per zone), 1 data.

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.name_prefix}-rt-public" }
}

resource "aws_route_table" "app" {
  count = 2

  vpc_id = aws_vpc.this.id

  # Each application subnet goes out through the NAT in its own zone.
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[count.index].id
  }

  tags = { Name = "${var.name_prefix}-rt-app-${var.zone_suffixes[count.index]}" }
}

# No default route: the database and the cache never reach the internet.
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-rt-data" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "app" {
  count = 2

  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

resource "aws_route_table_association" "data" {
  count = 2

  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

# Gateway endpoints are free and keep S3 and DynamoDB traffic off the NAT.
resource "aws_vpc_endpoint" "gateway" {
  for_each = toset(["s3", "dynamodb"])

  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(aws_route_table.app[*].id, [aws_route_table.data.id])

  tags = { Name = "${var.name_prefix}-endpoint-${each.key}" }
}
