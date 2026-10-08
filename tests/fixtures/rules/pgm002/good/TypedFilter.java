package fixtures;

import jakarta.persistence.EntityManager;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.Query;

interface EventRepository {
    // JPQL: the ORM types the parameter from the path expression.
    @Query("select e from Event e where (:from is null or e.occurredAt >= :from)")
    List<Event> jpql(OffsetDateTime from);
}

class EventDao {
    void run(EntityManager em, Connection c) throws SQLException {
        em.createQuery("select e from Event e where :kind is null or e.kind = :kind");
        c.prepareStatement("select count(*) from event where (cast(? as timestamptz) is null or occurred_at >= ?)");
        c.prepareStatement("select count(*) from event where (?::timestamptz is null or occurred_at >= ?)");
        c.prepareStatement("select count(*) from event where occurred_at >= ?");
        c.prepareStatement("select count(*) from event where ? is not null");
        c.prepareStatement("select payload::text is null from event");
        c.prepareStatement("select payload ?? 'a' from event");
        // c.prepareStatement("select 1 where ? is null");
        String unknownNamed = "select * from event where (:from is null or occurred_at >= :from)";
        String prose = "value? is null";
        em.createNativeQuery("select count(*) from event where (cast(:from as timestamptz) is null or occurred_at >= :from)");
    }
}
