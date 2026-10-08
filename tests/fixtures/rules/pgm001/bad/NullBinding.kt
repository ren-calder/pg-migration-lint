package fixtures

import java.sql.PreparedStatement
import java.sql.Types

fun bind(ps: PreparedStatement, id: Long?) {
    if (id == null) ps.setNull(1, Types.NULL) else ps.setLong(1, id) // expect[PGM001]
}
