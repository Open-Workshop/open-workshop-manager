ALTER TABLE `reputation_votes`
    DROP INDEX `ix_reputation_votes_target_type_target_id`,
    DROP INDEX `ix_reputation_votes_voter_created`;

ALTER TABLE `reputation_vote_history`
    DROP INDEX `ix_reputation_vote_history_target_created`;
