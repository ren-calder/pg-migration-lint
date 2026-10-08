package fixtures;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.Collections;
import java.util.List;

class DynamicIn {
    void byIds(Connection c, List<Long> ids) throws SQLException {
        String placeholders = String.join(",", Collections.nCopies(ids.size(), "?"));
        String sql = "select * from customer where customer_id in (" + placeholders + ")"; // expect[PGM004]
        c.prepareStatement(sql);
    }

    String byStatus(List<String> statuses) {
        return String.format("select * from account where status in (%s)", String.join(",", statuses)); // expect[PGM004]
    }

    void builder(StringBuilder sb, List<String> statuses) {
        sb.append("select * from account where 1 = 1");
        sb.append(" and status in ("); // expect[PGM004]
        sb.append(String.join(",", statuses)).append(")");
    }

    String notIn(String ids) {
        return "delete from account where id not in (" + ids + ")"; // expect[PGM004]
    }
}
