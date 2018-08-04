alter type score_mode add value 'max_subtask';

begin;

alter table submission_results add subtask_scores double precision[];
alter table submission_results add public_subtask_scores double precision[];

rollback; -- change this to: commit;
