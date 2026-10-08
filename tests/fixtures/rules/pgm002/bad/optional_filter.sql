-- Query file loaded by a JDBC repository.
select count(*)
from event
where (? is null or occurred_at >= ?); -- expect[PGM002]
