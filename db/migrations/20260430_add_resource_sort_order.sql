ALTER TABLE `resources`
    ADD COLUMN `sort_order` INT NOT NULL DEFAULT 0 AFTER `type`;

CREATE INDEX ix_resources_owner_type_owner_id_sort_order
    ON resources (owner_type, owner_id, sort_order, id);

DROP INDEX ix_resources_owner_type_owner_id
    ON resources;
