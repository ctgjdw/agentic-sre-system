resource "aws_db_subnet_group" "demo" {
  name        = "${var.project}-db-subnet-group"
  description = "Private subnets for the demo RDS instance"
  subnet_ids  = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = { Name = "${var.project}-db-subnet-group" }
}

resource "aws_db_parameter_group" "demo" {
  name        = "${var.project}-pg16"
  family      = "postgres16"
  description = "Postgres 16 default parameters for the demo"
}

resource "aws_db_instance" "demo" {
  identifier              = "${var.project}-db"
  engine                  = "postgres"
  engine_version          = "16.6"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = "opensre_demo"
  username                = "opensre"
  password                = var.db_password
  port                    = 5432
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 0
  skip_final_snapshot     = true

  db_subnet_group_name   = aws_db_subnet_group.demo.name
  parameter_group_name   = aws_db_parameter_group.demo.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  apply_immediately = true

  tags = { Name = "${var.project}-db" }
}
