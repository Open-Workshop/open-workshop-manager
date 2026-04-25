CREATE INDEX ix_sessions_access_refresh_broken
    ON sessions (access_token(72), refresh_token(72), broken(16));

CREATE INDEX ix_unity_mods_dependencies_mod_dependence
    ON unity_mods_dependencies (mod_id, dependence);

CREATE INDEX ix_unity_mods_dependencies_dependence_mod
    ON unity_mods_dependencies (dependence, mod_id);

CREATE INDEX ix_resources_owner_type_owner_id
    ON resources (owner_type, owner_id);

CREATE INDEX ix_mods_and_authors_user_mod
    ON mods_and_authors (user_id, mod_id);

CREATE INDEX ix_mods_and_authors_mod_user
    ON mods_and_authors (mod_id, user_id);
