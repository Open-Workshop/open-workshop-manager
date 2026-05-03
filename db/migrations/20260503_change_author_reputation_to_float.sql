ALTER TABLE `accounts`
    MODIFY COLUMN `reputation` DOUBLE NOT NULL DEFAULT 0 AFTER `last_password_reset`;

ALTER TABLE `reputation_vote_history`
    MODIFY COLUMN `reputation_delta` DOUBLE NOT NULL AFTER `value`;
