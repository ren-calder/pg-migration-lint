select * from t where id in (); -- pgmig-lint: ignore[PGM003]
select * from t where id in ('a', null); -- pgmig-lint: ignore[PGM003] expect[PGM008]
