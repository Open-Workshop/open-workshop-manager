-- Run against the catalog database. Build online while writes continue.
ALTER TABLE mods
    ADD INDEX ix_mods_visible_created (`condition`, public, date_creation),
    ALGORITHM=INPLACE, LOCK=NONE;
