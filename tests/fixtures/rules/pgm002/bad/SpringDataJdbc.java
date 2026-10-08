package fixtures;

import java.util.List;
import org.springframework.data.jdbc.repository.query.Query;

interface EventRepository {
    @Query("select * from event where (:from is null or occurred_at >= :from)") // expect[PGM002]
    List<Event> findFrom(java.time.OffsetDateTime from);
}
