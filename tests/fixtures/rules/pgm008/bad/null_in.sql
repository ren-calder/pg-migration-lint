select count(*) from account where legacy_active in ('Y', null); -- expect[PGM008]
select * from t where status in (NULL, 'A'); -- expect[PGM008]
