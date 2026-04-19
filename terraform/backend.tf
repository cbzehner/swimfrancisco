terraform {
  backend "s3" {
    bucket = "swimfrancisco-tfstate"
    key    = "swimfrancisco/terraform.tfstate"
    region = "auto"
    endpoints = {
      s3 = "https://d985f954e272a26b858d9f8c5fc53217.r2.cloudflarestorage.com"
    }
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_path_style              = true
    use_lockfile                = true
  }
}
