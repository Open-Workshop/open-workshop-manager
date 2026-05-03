DELETE rvh
FROM reputation_vote_history rvh
JOIN reputation_vote_history newer
    ON newer.voter_id = rvh.voter_id
   AND newer.target_type = rvh.target_type
   AND newer.target_id = rvh.target_id
   AND (
       newer.created_at > rvh.created_at
       OR (newer.created_at = rvh.created_at AND newer.id > rvh.id)
   );

CREATE UNIQUE INDEX ux_reputation_vote_history_voter_target
    ON reputation_vote_history (voter_id, target_type, target_id);
