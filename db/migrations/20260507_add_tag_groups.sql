CREATE TABLE `tag_groups` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(128) NOT NULL,
    PRIMARY KEY (`id`)
);

ALTER TABLE `tags`
    ADD COLUMN `group_id` INT NULL,
    ADD CONSTRAINT `fk_tags_group_id`
        FOREIGN KEY (`group_id`) REFERENCES `tag_groups` (`id`);

CREATE INDEX `ix_tags_group_id_name_id`
    ON `tags` (`group_id`, `name`, `id`);

CREATE INDEX `ix_allowed_mods_tags_game_tag`
    ON `unity_allowed_mods_tags` (`game_id`, `tag_id`);

CREATE INDEX `ix_allowed_mods_tags_tag_game`
    ON `unity_allowed_mods_tags` (`tag_id`, `game_id`);
