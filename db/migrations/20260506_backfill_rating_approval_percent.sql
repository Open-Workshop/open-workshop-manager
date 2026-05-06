UPDATE mods AS m
LEFT JOIN (
    SELECT
        target_id,
        ROUND(
            SUM(CASE WHEN value > 0 THEN 1 ELSE 0 END) * 100 / COUNT(*)
        ) AS approval_rating
    FROM reputation_votes
    WHERE target_type = 'mod'
    GROUP BY target_id
) AS votes ON votes.target_id = m.id
SET m.rating = COALESCE(votes.approval_rating, 0);

UPDATE modpacks AS mp
LEFT JOIN (
    SELECT
        target_id,
        ROUND(
            SUM(CASE WHEN value > 0 THEN 1 ELSE 0 END) * 100 / COUNT(*)
        ) AS approval_rating
    FROM reputation_votes
    WHERE target_type = 'modpack'
    GROUP BY target_id
) AS votes ON votes.target_id = mp.id
SET mp.rating = COALESCE(votes.approval_rating, 0);

ALTER TABLE accounts
    ADD COLUMN rating INT NOT NULL DEFAULT 0 AFTER reputation;

ALTER TABLE accounts
    ADD COLUMN votes_count INT NOT NULL DEFAULT 0 AFTER rating;

UPDATE accounts AS a
LEFT JOIN (
    SELECT
        target_id,
        ROUND(
            SUM(CASE WHEN value > 0 THEN 1 ELSE 0 END) * 100 / COUNT(*)
        ) AS approval_rating,
        COUNT(*) AS votes_count
    FROM reputation_votes
    WHERE target_type = 'profile'
    GROUP BY target_id
) AS votes ON votes.target_id = a.id
SET a.rating = COALESCE(votes.approval_rating, 0),
    a.votes_count = COALESCE(votes.votes_count, 0);
