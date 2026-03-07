-- Initial database setup for OCMRI Billing Reconciliation
-- This runs automatically when the PostgreSQL container starts for the first time.

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- trigram similarity for fuzzy text search
