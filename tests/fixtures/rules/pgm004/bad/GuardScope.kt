package fixtures

import org.springframework.jdbc.core.JdbcTemplate

fun guarded(jdbc: JdbcTemplate, ids: List<Long>): List<Map<String, Any>> {
    if (ids.isEmpty()) return emptyList()
    return jdbc.queryForList("select * from customer where id in (${ids.joinToString()})")
}

fun unguarded(jdbc: JdbcTemplate, ids: List<Long>) =
    jdbc.queryForList("select * from customer where id in (${ids.joinToString()})") // expect[PGM004]

fun withLambda(jdbc: JdbcTemplate, groups: List<List<Long>>) {
    jdbc.execute("set search_path to app")
    groups.forEach { ids ->
        if (ids.isNotEmpty()) {
            jdbc.queryForList("select * from customer where id in (${ids.joinToString()})")
        }
    }
}
