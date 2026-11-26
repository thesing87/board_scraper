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
        site = c.getApplicationContext().getString(R.string.site_url);
    }

    // ---------- 설정
    String url() { return p.getString("url", ""); }
    void setUrl(String u) { p.edit().putString("url", u).apply(); }
    boolean enabled() { return p.getBoolean("enabled", true); }

    /** 앱이 여는 가계부 주소: 고정 (res/values/strings.xml의 site_url, 시험용 debug 빌드는 src/debug에서 에뮬레이터용 주소) */
    private final String site;
    String site() { return site; }

    /** 아래쪽 탭: 마지막으로 본 화면 (0 가계부, 1 근무표). 앱을 다시 열면 그 탭부터 */
    int tab() { return p.getInt("tab", 0); }
    void setTab(int t) { p.edit().putInt("tab", t).apply(); }

    /** 주소의 앞부분 (https://집주소:포트) */
    static String origin(String url) {
        if (url == null) return "";
        int scheme = url.indexOf("://");
        if (scheme < 0) return "";
        int path = url.indexOf('/', scheme + 3);
        return (path < 0 ? url : url.substring(0, path)).toLowerCase(java.util.Locale.ROOT);
    }
    void setEnabled(boolean on) { p.edit().putBoolean("enabled", on).apply(); }

    // ---------- 금액 인식 알림: 확인 대기함에 넣으면 알림 (처음엔 켜짐), 못 보낸 것도 알림 (처음엔 꺼짐), 알림 권한을 물어봤는지
    boolean alertOn() { return p.getBoolean("alert", true); }
    void setAlertOn(boolean on) { p.edit().putBoolean("alert", on).apply(); }
    boolean alertPendingOn() { return p.getBoolean("alert_pending", false); }
    void setAlertPendingOn(boolean on) { p.edit().putBoolean("alert_pending", on).apply(); }
    /** 근무표 변경 알림 (FCM, DutyPush) */
    boolean dutyPushOn() { return p.getBoolean("duty_push", true); }
    void setDutyPushOn(boolean on) { p.edit().putBoolean("duty_push", on).apply(); }
    /** 가계부 변경 알림 (1.14부터, FCM, DutyPush) */
    boolean ledgerPushOn() { return p.getBoolean("ledger_push", true); }
    void setLedgerPushOn(boolean on) { p.edit().putBoolean("ledger_push", on).apply(); }
    /** 근무표 달력에 휴대폰 캘린더 일정 보이기 (1.16부터, 처음엔 꺼짐), 보이지 않을 캘린더 id들 */
    boolean calendarOn() { return p.getBoolean("calendar_on", false); }
    void setCalendarOn(boolean on) { p.edit().putBoolean("calendar_on", on).apply(); }
    java.util.Set<String> calendarHidden() { return new java.util.HashSet<>(p.getStringSet("calendar_hidden", new java.util.HashSet<>())); }
    void setCalendarShown(String id, boolean shown) {
        java.util.Set<String> s = calendarHidden();
        if (shown) s.remove(id); else s.add(id);
        p.edit().putStringSet("calendar_hidden", s).apply();
    }
    /** 근무표·가계부 변경 알림 중 하나라도 켜져 있으면 서버에 토큰을 등록해 둠 */
    boolean anyPushOn() { return dutyPushOn() || ledgerPushOn(); }
    /** 서버에 마지막으로 등록한 토큰·로그인 (같으면 다시 안 보냄) */
    String pushSent() { return p.getString("push_sent", ""); }
    long pushSentAt() { return p.getLong("push_sent_at", 0); }
    void setPushSent(String key) { p.edit().putString("push_sent", key).putLong("push_sent_at", System.currentTimeMillis()).apply(); }
    boolean askedDutyNotify() { return p.getBoolean("asked_duty_notify", false); }
    void setAskedDutyNotify() { p.edit().putBoolean("asked_duty_notify", true).apply(); }
    boolean askedNotifyPermission() { return p.getBoolean("asked_notify", false); }
    void setAskedNotifyPermission() { p.edit().putBoolean("asked_notify", true).apply(); }

    // ---------- 업데이트: 설치 결과 글, 확인 창을 취소한 때와 그 버전
    String updateMessage() { return p.getString("update_msg", ""); }
    void setUpdateMessage(String m) { p.edit().putString("update_msg", m).commit(); }
    long updateDeclinedAt() { return p.getLong("update_declined", 0); }
    /** 취소한 새 버전 (1.19부터 — 그 전에 남은 취소는 버전이 0이라 막지 않음) */
    long updateDeclinedVersion() { return p.getLong("update_declined_ver", 0); }
    void setUpdateDeclined(long t, long versionCode) {
        p.edit().putLong("update_declined", t).putLong("update_declined_ver", versionCode).commit();
    }
    void clearUpdateDeclined() { p.edit().remove("update_declined").remove("update_declined_ver").commit(); }

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

    // ---------- 무시할 알림: 알림 글에 이 표현이 있으면 가계부로 보내지 않음 (이 휴대폰에만, 띄어쓰기·대소문자 무시)
    static final int IGNORE_MAX = 50;
    static final int IGNORE_LEN = 30;

    static String norm(String s) {
        return s == null ? "" : s.replaceAll("\\s+", "").toLowerCase(java.util.Locale.ROOT);
    }

    List<String> ignores() {
        synchronized (LOCK) {
            JSONArray a = arr("ignores");
            List<String> out = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) if (!a.optString(i).isEmpty()) out.add(a.optString(i));
            return out;
        }
    }

    /** 표현 추가. 결과 글 (비었음·김·이미 있음·가득 참이면 그 이유, 넣었으면 null) */
    String addIgnore(String word) {
        String w = word == null ? "" : word.trim().replaceAll("\\s+", " ");
        if (norm(w).isEmpty()) return "표현을 넣어 주세요";
        if (w.length() > IGNORE_LEN) return IGNORE_LEN + "자까지 넣을 수 있어요";
        synchronized (LOCK) {
            List<String> list = ignores();
            for (String old : list) if (norm(old).equals(norm(w))) return "이미 있는 표현이에요";
            if (list.size() >= IGNORE_MAX) return IGNORE_MAX + "개까지 넣을 수 있어요";
            list.add(w);
            put("ignores", new JSONArray(list));
            return null;
        }
    }

    void removeIgnore(String word) {
        synchronized (LOCK) {
            List<String> list = ignores();
            list.removeIf(w -> w.equals(word));
            put("ignores", new JSONArray(list));
        }
    }

    /** 이 글을 거르는 표현 (없으면 null) */
    String ignoredBy(String text) {
        String t = norm(text);
        for (String w : ignores()) if (!norm(w).isEmpty() && t.contains(norm(w))) return w;
        return null;
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

    /** 줄의 알림 중 '못 보냄'을 아직 알리지 않은 것을 알렸다고 표시하고 돌려줌 (같은 결제를 여러 번 알리지 않게) */
    List<JSONObject> takeUnwarned() {
        synchronized (LOCK) {
            JSONArray q = arr("queue");
            List<JSONObject> out = new ArrayList<>();
            for (int i = 0; i < q.length(); i++) {
                JSONObject item = q.optJSONObject(i);
                if (item == null || item.optBoolean("warned")) continue;
                try { item.put("warned", true); } catch (JSONException ignored) { }
                out.add(item);
            }
            if (!out.isEmpty()) put("queue", q);
            return out;
        }
    }

    int waiting() {
        synchronized (LOCK) { return arr("queue").length(); }
    }

    // ---------- 최근 보낸 알림 기록 (새 것이 앞)
    void log(String app, String text, String status, boolean ok) { log(app, text, status, ok, false); }

    /** filtered: 무시할 표현에 걸려 보내지 않은 알림. full은 '이런 알림 안 받기'에서 낱말을 고를 때 쓰는 글 (휴대폰 안에만) */
    void log(String app, String text, String status, boolean ok, boolean filtered) {
        synchronized (LOCK) {
            JSONArray old = arr("log"), log = new JSONArray();
            try {
                String flat = text.replaceAll("\\s+", " ").trim();
                String preview = flat.length() > 70 ? flat.substring(0, 70) + "…" : flat;
                // 거른 알림은 '그래도 보내기'로 그대로 보낼 수 있게 글 전체 (결제 알림으로 치는 2000자까지, 줄바꿈도 그대로)
                String full = filtered ? text : flat.length() > 300 ? flat.substring(0, 300) : flat;
                log.put(new JSONObject().put("t", System.currentTimeMillis()).put("app", app)
                        .put("text", preview).put("full", full)
                        .put("status", status).put("ok", ok).put("filtered", filtered));
            } catch (JSONException ignored) { }
            for (int i = 0; i < old.length() && log.length() < LOG_MAX; i++) log.put(old.opt(i));
            put("log", log);
        }
    }

    /** 거른 알림을 '그래도 보내기'로 보냈다고 표시 (버튼을 숨겨 두 번 보내지 않게). 이미 보냈거나 없으면 false */
    boolean markResent(long t, String full) {
        synchronized (LOCK) {
            JSONArray a = arr("log");
            for (int i = 0; i < a.length(); i++) {
                JSONObject l = a.optJSONObject(i);
                if (l == null || l.optLong("t") != t || !full.equals(l.optString("full")) || !l.optBoolean("filtered")) continue;
                if (l.optBoolean("resent")) return false;
                try {
                    l.put("resent", true).put("status", l.optString("status").replaceFirst(" — 휴대폰 밖으로 안 나감$", "") + " → 그래도 보냄");
                } catch (JSONException ignored) { }
                put("log", a);
                return true;
            }
            return false;
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
