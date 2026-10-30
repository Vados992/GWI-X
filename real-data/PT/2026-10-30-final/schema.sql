
PRAGMA foreign_keys=ON;
CREATE TABLE snapshots(snapshot_id TEXT PRIMARY KEY, country TEXT NOT NULL, data_status TEXT NOT NULL);
CREATE TABLE requests(query_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots,
 url TEXT NOT NULL, status TEXT NOT NULL, retrieved_at TEXT NOT NULL, source_updated TEXT, sha256 TEXT);
CREATE TABLE observations(concept TEXT NOT NULL, period INTEGER NOT NULL, country TEXT NOT NULL,
 reference_year INTEGER NOT NULL, value_decimal TEXT, raw_value_decimal TEXT, unit TEXT NOT NULL,
 accounting_basis TEXT NOT NULL, source_flags TEXT NOT NULL, missing_reason TEXT NOT NULL,
 query_id TEXT NOT NULL REFERENCES requests, data_status TEXT NOT NULL,
 PRIMARY KEY(country,concept,period), CHECK(value_decimal IS NOT NULL OR missing_reason <> ''));
CREATE VIEW observed_values AS SELECT * FROM observations WHERE value_decimal IS NOT NULL;
CREATE TRIGGER immutable_observation_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_observation_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
