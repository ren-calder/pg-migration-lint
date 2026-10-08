package fixtures;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Properties;
import org.postgresql.ds.PGSimpleDataSource;

class DataSourceConfig {
    Connection open(String url) throws SQLException {
        Properties props = new Properties();
        props.setProperty("stringtype", "unspecified"); // expect[PGM007]
        PGSimpleDataSource ds = new PGSimpleDataSource();
        ds.setStringType("unspecified"); // expect[PGM007]
        String fixed = "jdbc:postgresql://localhost/app?stringtype=unspecified"; // expect[PGM007]
        return DriverManager.getConnection(url + "&stringtype=unspecified"); // expect[PGM007]
    }
}
