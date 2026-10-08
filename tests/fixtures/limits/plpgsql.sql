-- Function bodies in dollar quotes are treated as string literals and not analyzed.
create function f(x text) returns int language plpgsql as $$
begin
  return case x when null then 1 end;
end $$;
