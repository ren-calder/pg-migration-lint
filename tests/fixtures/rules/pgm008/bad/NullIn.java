package fixtures;

import java.sql.Connection;
import java.sql.SQLException;

class NullIn {
    void run(Connection c) throws SQLException {
        c.prepareStatement("select count(*) from account where legacy_active in ('Y', null)"); // expect[PGM008]
    }
}
