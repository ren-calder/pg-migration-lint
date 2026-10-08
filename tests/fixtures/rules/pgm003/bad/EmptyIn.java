package fixtures;

import java.sql.Connection;
import java.sql.SQLException;

class EmptyIn {
    void run(Connection c) throws SQLException {
        c.prepareStatement("select * from customer where customer_id in ()"); // expect[PGM003]
        c.prepareStatement("select * from customer where customer_id not in ( )"); // expect[PGM003]
        c.createStatement().executeQuery("select count(*) from account a "
                + "where a.status in (/* none yet */)"); // expect[PGM003]
    }
}
