-- psql variables are not bind parameters.
select * from event where :from is null;
select count(*) from event where (cast(? as timestamptz) is null or occurred_at >= ?);
-- where (? is null or occurred_at >= ?)
select '? is null';
