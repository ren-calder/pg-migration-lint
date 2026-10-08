package fixtures;

import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Types;

class NullBinding {
    void bind(PreparedStatement ps, Long customerId) throws SQLException {
        if (customerId == null) {
            ps.setNull(1, Types.NULL); // expect[PGM001]
        } else {
            ps.setLong(1, customerId);
        }
        ps.setNull(2, java.sql.Types.NULL); // expect[PGM001]
        ps.setNull(3, // expect[PGM001]
                Types.NULL, "unknown");
    }
}
