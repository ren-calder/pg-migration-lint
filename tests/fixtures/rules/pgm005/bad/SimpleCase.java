package fixtures;

import java.sql.Connection;
import java.sql.SQLException;

class SimpleCase {
    void backfill(Connection c) throws SQLException {
        c.createStatement().executeUpdate(
                "update account set active = case legacy_active when 'Y' then true when null then null end"); // expect[PGM005]
    }
}
