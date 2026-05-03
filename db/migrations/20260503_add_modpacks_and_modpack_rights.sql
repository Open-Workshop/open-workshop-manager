ALTER TABLE `accounts`
    ADD COLUMN `publish_modpacks` BOOLEAN NOT NULL DEFAULT TRUE AFTER `publish_mods`,
    ADD COLUMN `change_authorship_modpacks` BOOLEAN NOT NULL DEFAULT FALSE AFTER `change_authorship_mods`,
    ADD COLUMN `change_self_modpacks` BOOLEAN NOT NULL DEFAULT TRUE AFTER `change_self_mods`,
    ADD COLUMN `change_modpacks` BOOLEAN NOT NULL DEFAULT FALSE AFTER `change_mods`,
    ADD COLUMN `delete_self_modpacks` BOOLEAN NOT NULL DEFAULT TRUE AFTER `delete_self_mods`,
    ADD COLUMN `delete_modpacks` BOOLEAN NOT NULL DEFAULT FALSE AFTER `delete_mods`;

CREATE TABLE `modpacks` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(128) NOT NULL,
    `short_description` VARCHAR(512) NULL,
    `description` TEXT NULL,
    `condition` INT NOT NULL DEFAULT 0,
    `public` INT NOT NULL DEFAULT 0,
    `adult` BOOLEAN NOT NULL DEFAULT FALSE,
    `rating` INT NOT NULL DEFAULT 0,
    `downloads` BIGINT NOT NULL DEFAULT 0,
    `date_creation` DATETIME NULL,
    `date_edit` DATETIME NULL,
    `source` VARCHAR(64) NOT NULL,
    `source_id` VARCHAR(255) NULL,
    `git_url` VARCHAR(512) NULL,
    `game` INT NULL,
    PRIMARY KEY (`id`),
    CONSTRAINT `fk_modpacks_game`
        FOREIGN KEY (`game`) REFERENCES `games` (`id`)
);

CREATE INDEX `ix_modpacks_source_id`
    ON `modpacks` (`source_id`);

CREATE TABLE `modpacks_and_authors` (
    `user_id` INT NOT NULL,
    `owner` BOOLEAN NOT NULL DEFAULT FALSE,
    `modpack_id` INT NOT NULL,
    CONSTRAINT `fk_modpacks_and_authors_user_id`
        FOREIGN KEY (`user_id`) REFERENCES `accounts` (`id`)
);

CREATE INDEX `ix_modpacks_and_authors_user_modpack`
    ON `modpacks_and_authors` (`user_id`, `modpack_id`);

CREATE INDEX `ix_modpacks_and_authors_modpack_user`
    ON `modpacks_and_authors` (`modpack_id`, `user_id`);
