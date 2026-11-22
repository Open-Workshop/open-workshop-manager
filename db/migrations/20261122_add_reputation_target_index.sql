-- Run against the catalog database.
ALTER TABLE reputation_votes
    ADD INDEX ix_reputation_votes_target_value (target_type, target_id, value),
    ALGORITHM=INPLACE, LOCK=NONE;
