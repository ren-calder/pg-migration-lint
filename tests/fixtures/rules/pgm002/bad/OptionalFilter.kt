package fixtures

import org.springframework.data.jpa.repository.Query
import java.time.OffsetDateTime

interface EventRepository {
    @Query(
        value = """
            select * from event e
            where (:from is null or e.occurred_at >= :from) -- expect[PGM002]
        """,
        nativeQuery = true,
    )
    fun findFrom(from: OffsetDateTime?): List<Event>
}
