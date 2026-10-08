package fixtures;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;

// Each statement below is a known false negative, documented in the README.
class NotReported {
    void run(Connection c, PreparedStatement ps, String json) throws SQLException {
        // setObject(i, null): no executed evidence in the book, so not reported.
        ps.setObject(1, null);
        // setString into a jsonb column (42804) needs the column type; not available statically.
        c.prepareStatement("insert into migration_fixture values (1, ?)").setString(1, json);
        // NOT IN with a NULL element was not executed for the book.
        c.prepareStatement("select * from account where legacy_active not in ('Y', null)");
        // char(1) compared with boolean (42883) needs the column type.
        c.prepareStatement("select count(*) from account where legacy_active = true");
    }
}
