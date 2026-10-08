package fixtures;

import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Types;

class TypedNull {
    void bind(PreparedStatement ps) throws SQLException {
        ps.setNull(1, Types.BIGINT);
        ps.setNull(2, Types.TIMESTAMP_WITH_TIMEZONE);
        ps.setNull(3, Types.VARCHAR);
        // ps.setNull(4, Types.NULL);
        /* ps.setNull(5, Types.NULL); */
        String doc = "call setNull(i, Types.NULL) only in tests";
        int nullType = Types.NULL;
    }

    void setNull(int index, int sqlType) {
    }
}
