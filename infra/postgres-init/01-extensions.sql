CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Integration tests run against a dedicated database so a failing run can never
-- corrupt the development dataset.
SELECT 'CREATE DATABASE zaolang_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zaolang_test')\gexec

\connect zaolang_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
