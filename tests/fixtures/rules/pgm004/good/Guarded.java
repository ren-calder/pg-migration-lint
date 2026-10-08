package fixtures;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;

class Guarded {
    List<Long> byIds(Connection c, List<Long> ids) throws SQLException {
        if (ids.isEmpty()) {
            return List.of();
        }
        String sql = "select * from customer where customer_id in (" + placeholders(ids) + ")";
        c.prepareStatement(sql);
        return ids;
    }

    String placeholders(List<Long> ids) {
        return String.join(",", java.util.Collections.nCopies(ids.size(), "?"));
    }
}
