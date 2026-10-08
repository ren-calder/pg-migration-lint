select * from customer where customer_id in (); -- expect[PGM003]

delete from account
where id in ( -- expect[PGM003]
);
