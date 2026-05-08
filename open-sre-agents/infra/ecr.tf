resource "aws_ecr_repository" "sut" {
  name                 = "${var.project}-sut"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true # demo: allow `terraform destroy` to wipe images.
}
