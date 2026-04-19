# API token is read from CLOUDFLARE_API_TOKEN env var.
# R2 credentials are read from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
# by the S3 backend (naming is an S3-backend quirk; these are R2 keys).
provider "cloudflare" {}
