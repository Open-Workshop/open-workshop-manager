ALTER TABLE `games`
    MODIFY COLUMN `source_id` VARCHAR(255) NULL AFTER `source`;

ALTER TABLE `mods`
    MODIFY COLUMN `source_id` VARCHAR(255) NULL AFTER `source`;

CREATE INDEX `ix_games_source_id`
    ON `games` (`source_id`);

CREATE INDEX `ix_mods_source_id`
    ON `mods` (`source_id`);
