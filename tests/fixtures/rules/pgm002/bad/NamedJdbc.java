package fixtures;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

class Reports {
    List<Map<String, Object>> run(NamedParameterJdbcTemplate jdbc, Map<String, Object> p) {
        return jdbc.queryForList("select * from event where (:from is null or occurred_at >= :from)", p); // expect[PGM002]
    }
}
