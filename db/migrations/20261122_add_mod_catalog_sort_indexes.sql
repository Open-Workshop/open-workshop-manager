-- Run against the catalog database. Both indexes can be built online.
ALTER TABLE mods
    ADD INDEX ix_mods_feed_downloads (`condition`, public, downloads),
    ADD INDEX ix_mods_game_downloads (`condition`, public, game, downloads),
    ALGORITHM=INPLACE, LOCK=NONE;
