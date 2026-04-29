-- MySQL stores BOOLEAN as TINYINT(1), so this migration makes the age flag
-- intent explicit and prevents any non-boolean values from being persisted.
ALTER TABLE mods
    MODIFY adult BOOLEAN NOT NULL DEFAULT FALSE,
    ADD CONSTRAINT chk_mods_adult_bool CHECK (adult IN (0, 1));
