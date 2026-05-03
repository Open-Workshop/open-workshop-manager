ALTER TABLE mods
    ADD COLUMN rating INT NOT NULL DEFAULT 0 AFTER downloads;

CREATE TABLE reputation_votes (
    id INT NOT NULL AUTO_INCREMENT,
    voter_id INT NOT NULL,
    target_type VARCHAR(16) NOT NULL,
    target_id INT NOT NULL,
    value INT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_reputation_votes_voter_id
        FOREIGN KEY (voter_id) REFERENCES accounts(id)
);

CREATE UNIQUE INDEX ux_reputation_votes_voter_target
    ON reputation_votes (voter_id, target_type, target_id);

CREATE INDEX ix_reputation_votes_target_type_target_id
    ON reputation_votes (target_type, target_id);

CREATE INDEX ix_reputation_votes_voter_created
    ON reputation_votes (voter_id, created_at);

CREATE TABLE reputation_vote_history (
    id INT NOT NULL AUTO_INCREMENT,
    voter_id INT NOT NULL,
    target_type VARCHAR(16) NOT NULL,
    target_id INT NOT NULL,
    target_name VARCHAR(128) NOT NULL,
    previous_value INT NOT NULL,
    value INT NOT NULL,
    reputation_delta INT NOT NULL,
    mod_delta INT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_reputation_vote_history_voter_id
        FOREIGN KEY (voter_id) REFERENCES accounts(id)
);

CREATE INDEX ix_reputation_vote_history_voter_created
    ON reputation_vote_history (voter_id, created_at);

CREATE INDEX ix_reputation_vote_history_target_created
    ON reputation_vote_history (target_type, target_id, created_at);
