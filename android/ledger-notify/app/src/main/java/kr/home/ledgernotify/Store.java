package kr.home.ledgernotify;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** 앱 설정과 상태 (SharedPreferences 하나). 알림 받기·보내기·화면이 여러 스레드에서 쓰므로 모두 LOCK 안에서 */
final class Store {
    static final Object LOCK = new Object();
    static final int QUEUE_MAX = 200;       // 못 보내고 기다리는 알림 (넘치면 오래된 것부터 버림)
    static final int LOG_MAX = 30;          // 화면의 '최근 보낸 알림'
    static final int RECENT_MAX = 60;       // 같은 알림 두 번 보내지 않기 위해 기억하는 수
    static final long DUP_MS = 10 * 60 * 1000L;

    private final SharedPreferences p;

    Store(Context c) {
        p = c.getApplicationContext().getSharedPreferences("ledger_notify", Context.MODE_PRIVATE);
    }

    // ---------- 설정
    String url() { return p.getString("url", ""); }
    void setUrl(String u) { p.edit().putString("url", u).apply(); }
    boolean enabled() { return p.getBoolean("enabled", true); }
    void setEnabled(boolean on) { p.edit().putBoolean("enabled", on).apply(); }

    // ---------- 업데이트: 설치 결과 글, 확인 창을 취소한 때
    String updateMessage() { return p.getString("update_msg", ""); }
    void setUpdateMessage(String m) { p.edit().putString("update_msg", m).commit(); }
    long updateDeclinedAt() { return p.getLong("update_declined", 0); }
    void setUpdateDeclinedAt(long t) { p.edit().putLong("update_declined", t).commit(); }

    // ---------- 알림을 보낸 앱 (앱마다 끌 수 있음). {pkg: {label, on, last}}
    JSONObject apps() { return obj("apps"); }

    /** 이 앱의 결제 알림을 보낼지. 처음 본 앱은 목록에 넣고 켬 */
    boolean appAllowed(String pkg, String label) {
        synchronized (LOCK) {
            JSONObject apps = apps();
            JSONObject a = apps.optJSONObject(pkg);
            try {
                if (a == null) {
                    a = new JSONObject().put("on", true);
                    apps.put(pkg, a);
                }
                a.put("label", label).put("last", System.currentTimeMillis());
            } catch (JSONException ignored) { }
            put("apps", apps);
            return a.optBoolean("on", true);
        }
    }

    void setAppOn(String pkg, boolean on) {
        synchronized (LOCK) {
            JSONObject apps = apps();
            JSONObject a = apps.optJSONObject(pkg);
            if (a == null) return;
            try { a.put("on", on); } catch (JSONException ignored) { }
            put("apps", apps);
        }
    }

    // ---------- 같은 알림 다시 오면 넘김 (글이 같고 10분 안)
    boolean seenRecently(String text) {
        synchronized (LOCK) {
            long now = System.currentTimeMillis();
            String key = Integer.toHexString(text.hashCode()) + ":" + text.length();
            JSONArray recent = arr("recent"), keep = new JSONArray();
            boolean seen = false;
            for (int i = 0; i < recent.length(); i++) {
                JSONObject r = recent.optJSONObject(i);
                if (r == null || now - r.optLong("t") > DUP_MS) continue;
                if (key.equals(r.optString("k"))) seen = true;
                keep.put(r);
            }
            if (!seen) {
                try { keep.put(new JSONObject().put("k", key).put("t", now)); } catch (JSONException ignored) { }
            }
            put("recent", tail(keep, RECENT_MAX));
            return seen;
        }
    }

    // ---------- 보낼 알림 줄
    void enqueue(String app, String text) {
        synchronized (LOCK) {
            JSONArray q = arr("queue");
            try {
                q.put(new JSONObject().put("app", app).put("text", text).put("t", System.currentTimeMillis()));
            } catch (JSONException ignored) { }
            put("queue", tail(q, QUEUE_MAX));
        }
    }

    JSONObject peek() {
        synchronized (LOCK) {
            JSONArray q = arr("queue");
            return q.length() > 0 ? q.optJSONObject(0) : null;
        }
    }

    void dropFirst() {
        synchronized (LOCK) {
            JSONArray q = arr("queue"), rest = new JSONArray();
            for (int i = 1; i < q.length(); i++) rest.put(q.opt(i));
            put("queue", rest);
        }
    }

    int waiting() {
        synchronized (LOCK) { return arr("queue").length(); }
    }

    // ---------- 최근 보낸 알림 기록 (새 것이 앞)
    void log(String app, String text, String status, boolean ok) {
        synchronized (LOCK) {
            JSONArray old = arr("log"), log = new JSONArray();
            try {
                String preview = text.replaceAll("\\s+", " ").trim();
                if (preview.length() > 70) preview = preview.substring(0, 70) + "…";
                log.put(new JSONObject().put("t", System.currentTimeMillis()).put("app", app)
                        .put("text", preview).put("status", status).put("ok", ok));
            } catch (JSONException ignored) { }
            for (int i = 0; i < old.length() && log.length() < LOG_MAX; i++) log.put(old.opt(i));
            put("log", log);
        }
    }

    List<JSONObject> logs() {
        synchronized (LOCK) {
            JSONArray a = arr("log");
            List<JSONObject> out = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) if (a.optJSONObject(i) != null) out.add(a.optJSONObject(i));
            return out;
        }
    }

    // ---------- JSON 도우미
    private JSONArray arr(String key) {
        try { return new JSONArray(p.getString(key, "[]")); } catch (JSONException e) { return new JSONArray(); }
    }

    private JSONObject obj(String key) {
        try { return new JSONObject(p.getString(key, "{}")); } catch (JSONException e) { return new JSONObject(); }
    }

    private void put(String key, Object v) {
        p.edit().putString(key, v.toString()).commit();
    }

    private static JSONArray tail(JSONArray a, int max) {
        if (a.length() <= max) return a;
        JSONArray out = new JSONArray();
        for (int i = a.length() - max; i < a.length(); i++) out.put(a.opt(i));
        return out;
    }
}
