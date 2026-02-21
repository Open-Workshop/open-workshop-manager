ALTER TABLE `mods`
    ADD COLUMN `size_unpacked` BIGINT NULL AFTER `size`;

ALTER TABLE `resources`
    ADD COLUMN `size` BIGINT NULL AFTER `url`;
