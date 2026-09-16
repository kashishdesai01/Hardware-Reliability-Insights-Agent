terraform {
  backend "s3" {
    # Supplied through backend.hcl; the bootstrap stack creates the bucket.
    use_lockfile = true
    encrypt      = true
  }
}
