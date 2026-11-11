locals {
  name_prefix     = var.project
  pg_dumps_prefix = "pg-dumps/"
  s3_prefixes = toset([
    "bdl-raw/",
    "bdl-archive/",
    "bdl-samples/",
    local.pg_dumps_prefix,
  ])
}
