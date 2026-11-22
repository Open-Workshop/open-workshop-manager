-- Run against the catalog database. Online index creation avoids blocking writes.
ALTER TABLE mods
    ADD INDEX ix_mods_feed_bounds (`condition`, public, game, size, size_unpacked),
    ALGORITHM=INPLACE, LOCK=NONE;
