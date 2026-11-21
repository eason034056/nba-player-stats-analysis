locals {
  # dev stays var.project so sportslab-postgres, sportslab-pg16, sportslab-rds,
  # sportslab-app, and sportslab-runtime do not change. A -dev suffix would
  # replace those resources. prod is not applied yet, so it can take a suffix.
  name_prefix     = var.environment == "dev" ? var.project : "${var.project}-${var.environment}"
  pg_dumps_prefix = "pg-dumps/"
  s3_prefixes = toset([
    "bdl-raw/",
    "bdl-archive/",
    "bdl-samples/",
    local.pg_dumps_prefix,
  ])
}
