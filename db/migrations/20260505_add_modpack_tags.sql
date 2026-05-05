CREATE TABLE `modpacks_tags` (
    `modpack_id` INT NOT NULL,
    `tag_id` INT NOT NULL,
    CONSTRAINT `fk_modpacks_tags_modpack_id`
        FOREIGN KEY (`modpack_id`) REFERENCES `modpacks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_modpacks_tags_tag_id`
        FOREIGN KEY (`tag_id`) REFERENCES `tags` (`id`) ON DELETE CASCADE
);

CREATE UNIQUE INDEX `ux_modpacks_tags_modpack_tag`
    ON `modpacks_tags` (`modpack_id`, `tag_id`);

CREATE INDEX `ix_modpacks_tags_tag_modpack`
    ON `modpacks_tags` (`tag_id`, `modpack_id`);
