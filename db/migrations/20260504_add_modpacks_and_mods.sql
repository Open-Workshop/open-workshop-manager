CREATE TABLE `modpacks_and_mods` (
    `modpack_id` INT NOT NULL,
    `mod_id` INT NOT NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `auto_added` BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT `fk_modpacks_and_mods_modpack_id`
        FOREIGN KEY (`modpack_id`) REFERENCES `modpacks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_modpacks_and_mods_mod_id`
        FOREIGN KEY (`mod_id`) REFERENCES `mods` (`id`) ON DELETE CASCADE
);

CREATE UNIQUE INDEX `ux_modpacks_and_mods_modpack_mod`
    ON `modpacks_and_mods` (`modpack_id`, `mod_id`);

CREATE INDEX `ix_modpacks_and_mods_modpack_sort`
    ON `modpacks_and_mods` (`modpack_id`, `sort_order`, `mod_id`);

CREATE INDEX `ix_modpacks_and_mods_mod_modpack`
    ON `modpacks_and_mods` (`mod_id`, `modpack_id`);
