package fixtures;

class Logging {
    void report(java.util.logging.Logger log) {
        log.info("stringtype=unspecified: setString resolves against bigint");
        log.info("setString to jsonb works only with stringtype=unspecified (global side effects)");
        // url + "&stringtype=unspecified"
    }
}
