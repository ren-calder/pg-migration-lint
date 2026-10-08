select 'in ()';
-- where id in ()
/* where id in () */
select $$ where id in () $$;
select "in ()" from t;
select * from t where id in (1, 2);
