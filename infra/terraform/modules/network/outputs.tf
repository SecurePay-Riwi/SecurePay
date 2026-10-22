output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "app_subnet_ids" {
  value = aws_subnet.app[*].id
}

output "data_subnet_ids" {
  value = aws_subnet.data[*].id
}

output "nat_public_ips" {
  description = "Public addresses the private subnets go out with."
  value       = aws_eip.nat[*].public_ip
}

output "private_route_table_ids" {
  value = concat(aws_route_table.app[*].id, [aws_route_table.data.id])
}
