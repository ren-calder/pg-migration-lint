package fixtures;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;
import java.util.logging.Logger;
import org.springframework.data.jpa.repository.Query;

interface CustomerRepository {
    @Query(value = "select * from customer where id in (:ids)", nativeQuery = true)
    List<Customer> byIds(List<Long> ids);
}

class StaticIn {
    private static final String ACTIVE = "'A','B'";
    private static final String BLOCKED = "select id from blocked";
    private static final Logger log = Logger.getLogger("x");

    void run(Connection c, String user) throws SQLException {
        c.prepareStatement("select * from account where status in (" + ACTIVE + ")");
        c.prepareStatement("select * from customer where id not in (" + BLOCKED + ")");
        c.prepareStatement("select * from customer where id = any (?::bigint[])");
        c.prepareStatement("select * from customer where id in (?, ?, ?)");
        log.info("user logged in (" + user + ")");
    }
}
