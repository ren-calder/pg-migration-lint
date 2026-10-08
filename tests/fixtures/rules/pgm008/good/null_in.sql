select * from t where status in ('null', 'A');
select * from t where status in (select null);
select * from t where coalesce(status, 'x') in ('a', 'b');
select * from t where status in (coalesce(a, null), 'x');
select * from t where status in ('Y') or status is null;
