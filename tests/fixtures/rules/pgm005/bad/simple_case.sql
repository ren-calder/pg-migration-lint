update account
set active = case legacy_active
    when 'Y' then true
    when 'N' then false
    when null then null -- expect[PGM005]
end;

select case kind when null::text then 'none' else kind end from t; -- expect[PGM005]

select case when a is null then case b when null then 1 end end from t; -- expect[PGM005]
