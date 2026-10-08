package fixtures

import org.springframework.jdbc.core.JdbcTemplate

fun byIds(jdbc: JdbcTemplate, ids: List<Long>) =
    jdbc.queryForList("select * from customer where customer_id in (${ids.joinToString()})") // expect[PGM004]

fun byCodes(jdbc: JdbcTemplate, codes: String) =
    jdbc.queryForList("""
        select * from product
        where code in ($codes) -- expect[PGM004]
    """.trimIndent())
