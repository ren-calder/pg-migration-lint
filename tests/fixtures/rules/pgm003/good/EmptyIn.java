package fixtures;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.logging.Logger;

class NotEmptyIn {
    private static final Logger log = Logger.getLogger("x");

    void run(Connection c) throws SQLException {
        log.info("Logged in ()");
        c.prepareStatement("select 'in ()' from customer");
        c.prepareStatement("select * from customer where customer_id in (?, ?)");
        c.prepareStatement("select 1 -- in ()\n from customer");
        c.prepareStatement("select * from customer where customer_id = any (?::bigint[])");
        c.prepareStatement("select * from customer where customer_id in (select id from vip)");
    }
}
