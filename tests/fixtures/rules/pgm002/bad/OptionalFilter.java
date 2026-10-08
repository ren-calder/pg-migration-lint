package fixtures;

import jakarta.persistence.EntityManager;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.Query;

interface EventRepository {
    @Query(value = "select * from event e where (:from is null or e.occurred_at >= :from)", // expect[PGM002]
           nativeQuery = true)
    List<Event> findFrom(OffsetDateTime from);

    @Query(nativeQuery = true, value = """
        select * from event e
        where (:status is null or e.status = :status) -- expect[PGM002]
        """)
    List<Event> findByStatus(String status);
}

class EventDao {
    private static final String OPTIONAL_FROM =
            "select count(*) from event where (:from is null or occurred_at >= :from)"; // expect[PGM002]

    long count(EntityManager em, Connection c, OffsetDateTime from) throws SQLException {
        em.createNativeQuery(OPTIONAL_FROM).setParameter("from", from).getSingleResult();
        String sql = "select count(*) from event where (? is null or occurred_at >= ?)"; // expect[PGM002]
        try (PreparedStatement ps = c.prepareStatement(sql)) {
            ps.executeQuery();
        }
        c.prepareStatement("select count(*) from event "
                + "where (? is null or occurred_at >= ?)"); // expect[PGM002]
        em.createNativeQuery("select * from event where ?1 is null or kind = ?1"); // expect[PGM002]
        return 0;
    }
}
