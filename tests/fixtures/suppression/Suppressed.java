package fixtures;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Types;

class Suppressed {
    void run(Connection c, PreparedStatement ps) throws SQLException {
        c.prepareStatement("select * from t where id in ()"); // pgmig-lint: ignore[PGM003]
        c.prepareStatement("select * from t where id in ()"); // pgmig-lint: ignore[PGM001] expect[PGM003]
        c.prepareStatement("select * from t where id in () -- pgmig-lint: ignore[PGM003]");
        String s = "pgmig-lint: ignore[PGM003]"; c.prepareStatement("select * from t where id in ()"); // expect[PGM003]
        ps.setNull(1, Types.NULL); // pgmig-lint: ignore[PGM003, pgm001]
    }
}
