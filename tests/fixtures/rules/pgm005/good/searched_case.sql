update account set active = case
    when legacy_active = 'Y' then true
    when legacy_active = 'N' then false
    when legacy_active is null then null
end;

select case kind when 'null' then 1 end from t;
select case when null then 1 end;
select coalesce(case kind when 'a' then null end, 'x') from t;
-- case x when null then 1 end
select case x when 1 then (case when y is null then 0 end) end from t;
