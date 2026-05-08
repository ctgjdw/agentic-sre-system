resource "aws_s3_bucket" "ui" {
  bucket        = "${var.project}-ui-${var.ui_bucket_suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket = aws_s3_bucket.ui.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

# Public-read bucket policy. Public website hosting requires either CloudFront
# (out of scope) or a public bucket policy.
data "aws_iam_policy_document" "ui_public_read" {
  statement {
    sid    = "PublicReadGetObject"
    effect = "Allow"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ui.arn}/*"]
  }
}

resource "aws_s3_bucket_policy" "ui" {
  bucket = aws_s3_bucket.ui.id
  policy = data.aws_iam_policy_document.ui_public_read.json

  depends_on = [aws_s3_bucket_public_access_block.ui]
}
