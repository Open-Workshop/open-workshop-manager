ALTER TABLE unity_mods_dependencies
    ADD COLUMN optional BOOLEAN NOT NULL DEFAULT FALSE AFTER dependence;

CREATE TABLE unity_mods_conflicts (
    mod_id INT NOT NULL,
    conflict INT NOT NULL,
    CONSTRAINT fk_unity_mods_conflicts_mod_id
        FOREIGN KEY (mod_id) REFERENCES mods(id),
    CONSTRAINT fk_unity_mods_conflicts_conflict
        FOREIGN KEY (conflict) REFERENCES mods(id)
);

CREATE INDEX ix_unity_mods_conflicts_mod_conflict
    ON unity_mods_conflicts (mod_id, conflict);

CREATE INDEX ix_unity_mods_conflicts_conflict_mod
    ON unity_mods_conflicts (conflict, mod_id);
