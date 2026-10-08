package fixtures;

import java.util.ArrayList;
import java.util.List;

class GuardScope {
    // The emptiness check below belongs to this method only.
    String restrict(List<Object> related) throws Exception {
        if (related.size() > 0) {
            throw new Exception("related rows exist");
        }
        return "";
    }

    String cascade(String key, List<Object> related) {
        List<Object> cols = new ArrayList<>();
        for (Object o : related) {
            if (o != null) {
                cols.add(o);
            }
        }
        StringBuilder where = new StringBuilder("WHERE " + key + " IN ("); // expect[PGM004]
        for (Object col : cols) {
            where.append(col).append(",");
        }
        return where.append(")").toString();
    }
}
