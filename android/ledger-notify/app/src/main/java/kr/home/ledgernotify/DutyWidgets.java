package kr.home.ledgernotify;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.os.Bundle;
import android.widget.RemoteViews;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 홈 화면 근무표 위젯 두 가지 (한 달 DutyMonthWidget, 작게 DutyTodayWidget)의 공통 부분.
 * - 데이터: 앱 안 가계부 로그인(쿠키)으로 /api/ledger/duty?month=이번 달&person=위젯마다 고른 사람 → 위젯마다 마지막 답을 저장해 두고
 *   인터넷이 안 될 때는 그것으로 그림
 * - 그리기: 근무 색을 그대로 쓰려고 위젯 크기만 한 그림(Bitmap)을 그려 ImageView에 넣음
 * - 새로: 3시간마다(위젯 설정), 자정 조금 뒤(알람), 앱에서 근무표를 고쳤을 때(DutyWidgets.refreshAll)
 * - 휴대폰 캘린더 일정 (1.18부터): 근무표 설정 > 구글 캘린더를 켰으면 앱 달력처럼 일정 이름도 (PhoneCalendar, 숨긴 캘린더는 빼고).
 *   캘린더가 바뀌면 CalendarWatch가 곧 다시 그림
 * - 누르면 앱의 근무표 탭
 */
final class DutyWidgets {
    static final String ACTION_REFRESH = "kr.home.ledgernotify.DUTY_WIDGET_REFRESH";
    private static final String PREFS = "duty_widgets";
    private static final String WD = "일월화수목금토";
    private static final int GREEN = 0xFF0F6E56, TEXT = 0xFF111827, MUTED = 0xFF5F6673, FAINT = 0xFF8B919C;
    private static final int SUN = 0xFFD85A30, SAT = 0xFF378ADD;

    private DutyWidgets() {}

    // ==========================================
    // 위젯마다 고른 사람·마지막 답
    // ==========================================
    private static SharedPreferences prefs(Context c) {
        return c.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static void setPerson(Context c, int id, int personId) {
        prefs(c).edit().putInt("p_" + id, personId).remove("c_" + id).apply();
    }

    static int person(Context c, int id) {
        return prefs(c).getInt("p_" + id, 0);
    }

    /** 근무표 설정 > 이 휴대폰 > 처음 보일 사람 (위젯을 놓을 때 맨 위에 보임) */
    static void setDefaultPerson(Context c, int personId) {
        prefs(c).edit().putInt("default_person", personId).apply();
    }

    static int defaultPerson(Context c) {
        return prefs(c).getInt("default_person", 0);
    }

    static void forget(Context c, int[] ids) {
        SharedPreferences.Editor e = prefs(c).edit();
        for (int id : ids) e.remove("p_" + id).remove("c_" + id).remove("e_" + id);
        e.apply();
    }

    // ==========================================
    // 서버
    // ==========================================
    /** 로그인 쿠키 (없으면 null) */
    static String cookie(Context c) {
        String origin = Store.origin(new Store(c).site());
        if (origin.isEmpty()) return null;
        try {
            String k = android.webkit.CookieManager.getInstance().getCookie(origin + "/api/ledger/");
            return k != null && k.contains("ledger_session=") ? k : null;
        } catch (Exception e) {
            return null;     // 웹 화면 구성 요소가 없는 휴대폰 등
        }
    }

    /** /api/ledger/duty 답. 로그인이 안 됐으면 예외 메시지 'login' */
    static JSONObject fetch(Context c, int personId) throws Exception {
        String origin = Store.origin(new Store(c).site());
        String cookie = cookie(c);
        if (origin.isEmpty() || cookie == null) throw new Exception("login");
        String month = new SimpleDateFormat("yyyy-MM", Locale.ROOT).format(new Date());
        String url = origin + "/api/ledger/duty?month=" + month + (personId > 0 ? "&person=" + personId : "");
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setRequestProperty("Cookie", cookie);
        con.setRequestProperty("Accept", "application/json");
        try {
            con.setConnectTimeout(8000);
            con.setReadTimeout(10000);
            int code = con.getResponseCode();
            if (code == 401) throw new Exception("login");
            if (code != 200) throw new java.io.IOException("HTTP " + code);
            try (InputStream in = con.getInputStream()) {
                ByteArrayOutputStream b = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0 && b.size() < 262144) b.write(buf, 0, n);
                return new JSONObject(b.toString("UTF-8"));
            }
        } finally {
            con.disconnect();
        }
    }

    // ==========================================
    // 새로 그리기
    // ==========================================
    /** 두 가지 위젯 모두 새로 (서버에서 다시 받음). 앱에서 근무표를 고쳤을 때·자정 알람 */
    static void refreshAll(Context c) {
        Context app = c.getApplicationContext();
        AppWidgetManager m = AppWidgetManager.getInstance(app);
        int[] month = m.getAppWidgetIds(new ComponentName(app, DutyMonthWidget.class));
        int[] today = m.getAppWidgetIds(new ComponentName(app, DutyTodayWidget.class));
        if (month.length + today.length == 0) return;
        new Thread(() -> {
            update(app, m, month, true);
            update(app, m, today, true);
        }).start();
    }

    /** 서버에서 다시 받지 않고 저장해 둔 답으로만 다시 그림 (캘린더 일정이 바뀜) */
    static void redrawAll(Context c) {
        Context app = c.getApplicationContext();
        AppWidgetManager m = AppWidgetManager.getInstance(app);
        for (Class<?> k : new Class<?>[]{DutyMonthWidget.class, DutyTodayWidget.class}) {
            for (int id : m.getAppWidgetIds(new ComponentName(app, k))) draw(app, m, id);
        }
        CalendarWatch.schedule(app);
    }

    static boolean any(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        return m.getAppWidgetIds(new ComponentName(c, DutyMonthWidget.class)).length
                + m.getAppWidgetIds(new ComponentName(c, DutyTodayWidget.class)).length > 0;
    }

    /** 저장해 둔 답으로 바로 그리고, fetch면 서버에서 받아 다시 그림 (부르는 쪽에서 백그라운드로) */
    static void update(Context c, AppWidgetManager m, int[] ids, boolean fetch) {
        for (int id : ids) draw(c, m, id);
        if (fetch) {
            for (int id : ids) {
                SharedPreferences.Editor e = prefs(c).edit();
                try {
                    JSONObject data = fetch(c, person(c, id));
                    e.putString("c_" + id, data.toString()).remove("e_" + id);
                } catch (Exception ex) {
                    e.putString("e_" + id, "login".equals(ex.getMessage()) ? "login" : "net");
                }
                e.commit();
                draw(c, m, id);
            }
        }
        scheduleMidnight(c);
        CalendarWatch.schedule(c);
    }

    private static void draw(Context c, AppWidgetManager m, int id) {
        boolean small = m.getAppWidgetInfo(id) != null
                && DutyTodayWidget.class.getName().equals(m.getAppWidgetInfo(id).provider.getClassName());
        Bundle o = m.getAppWidgetOptions(id);
        float d = c.getResources().getDisplayMetrics().density;
        // 세로 화면 기준 크기: 폭은 최소 폭, 높이는 최대 높이
        int wdp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, small ? 180 : 280);
        int hdp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, small ? 70 : 280);
        if (wdp < 60) wdp = small ? 180 : 280;
        if (hdp < 40) hdp = small ? 70 : 280;
        float scale = Math.min(d, 2.5f);
        Bitmap bmp = Bitmap.createBitmap(Math.round(wdp * scale), Math.round(hdp * scale), Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(bmp);
        cv.scale(scale, scale);
        Painter p = new Painter(cv, wdp, hdp);
        p.background();

        String cached = prefs(c).getString("c_" + id, null);
        String err = prefs(c).getString("e_" + id, null);
        JSONObject data = null;
        try { if (cached != null) data = new JSONObject(cached); } catch (Exception ignored) { /* 깨진 저장 */ }
        if (data == null || data.optJSONArray("people") == null) {
            p.message("login".equals(err) ? "YeYe홈 앱에서 가계부에 로그인해 주세요" : err != null ? "근무표를 불러오지 못했어요 · 눌러서 앱 열기" : "불러오는 중…");
        } else if (data.optJSONArray("people").length() == 0) {
            p.message("근무표에 사람이 없어요 · 눌러서 앱에서 더하기");
        } else {
            Roster r = new Roster(data);
            r.loadEvents(c);
            if (small) p.today(r); else p.month(r);
            if (err != null) p.stale("login".equals(err) ? "로그인 필요" : "연결 안 됨");
        }

        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.duty_widget);
        v.setImageViewBitmap(R.id.duty_widget_image, bmp);
        v.setContentDescription(R.id.duty_widget_image, "근무표");
        Intent open = new Intent(c, MainActivity.class).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_DUTY)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        v.setOnClickPendingIntent(R.id.duty_widget_image,
                PendingIntent.getActivity(c, 7000 + id, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        m.updateAppWidget(id, v);
    }

    /** 자정 조금 뒤 한 번 새로 (날짜가 바뀌면 '오늘'이 바뀜). 정확할 필요는 없어 권한이 필요 없는 알람 */
    private static void scheduleMidnight(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        Calendar at = Calendar.getInstance();
        at.add(Calendar.DAY_OF_MONTH, 1);
        at.set(Calendar.HOUR_OF_DAY, 0);
        at.set(Calendar.MINUTE, 2);
        at.set(Calendar.SECOND, 0);
        Intent i = new Intent(c, DutyMonthWidget.class).setAction(ACTION_REFRESH);
        PendingIntent pi = PendingIntent.getBroadcast(c, 7999, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        am.set(AlarmManager.RTC, at.getTimeInMillis(), pi);
    }

    // ==========================================
    // 받은 근무표 읽기
    // ==========================================
    private static final class Type {
        String code, name, time;
        int color;
    }

    private static final class Roster {
        final String month, today, personName;
        final Map<Integer, Type> types = new HashMap<>();
        final Map<String, Integer> days = new HashMap<>();

        Roster(JSONObject d) {
            month = d.optString("month");
            String t = d.optString("today");
            // 받은 뒤 날짜가 바뀌었으면 휴대폰 날짜로
            String now = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).format(new Date());
            today = now.compareTo(t) > 0 ? now : t;
            JSONArray ts = d.optJSONArray("types");
            for (int i = 0; ts != null && i < ts.length(); i++) {
                JSONObject o = ts.optJSONObject(i);
                Type ty = new Type();
                ty.code = o.optString("code");
                ty.name = o.optString("name");
                String s = o.optString("start_time");
                ty.time = s.isEmpty() ? "" : s + "–" + o.optString("end_time");
                try { ty.color = Color.parseColor(o.optString("color")); } catch (Exception e) { ty.color = 0xFF888780; }
                types.put(o.optInt("id"), ty);
            }
            String name = "";
            JSONArray ps = d.optJSONArray("people");
            for (int i = 0; ps != null && i < ps.length(); i++) {
                if (ps.optJSONObject(i).optInt("id") == d.optInt("person_id")) name = ps.optJSONObject(i).optString("name");
            }
            personName = name;
            for (String key : new String[]{"days", "near"}) {
                JSONObject m = d.optJSONObject(key);
                if (m == null) continue;
                for (java.util.Iterator<String> it = m.keys(); it.hasNext(); ) {
                    String day = it.next();
                    days.put(day, m.optInt(day));
                }
            }
        }

        Type at(String day) {
            Integer t = days.get(day);
            return t == null ? null : types.get(t);
        }

        /** 날짜마다 휴대폰 캘린더 일정 (켜 두고 권한이 있을 때만). 여러 날 일정은 날마다, 종일 일정이 먼저 */
        final Map<String, List<Ev>> events = new HashMap<>();

        void loadEvents(Context c) {
            Store s = new Store(c);
            if (!s.calendarOn() || !PhoneCalendar.allowed(c) || month.length() != 7) return;
            String from = month + "-01";
            String to = addDays(addDays(from, 31).substring(0, 7) + "-01", -1);   // 그 달 마지막 날
            if (today.compareTo(to) > 0) to = today;   // 받은 뒤 달이 바뀜
            try {
                JSONArray list = PhoneCalendar.events(c, from, to, s.calendarHidden());
                for (int i = 0; i < list.length(); i++) {
                    JSONObject o = list.optJSONObject(i);
                    Ev e = new Ev();
                    e.title = o.optString("title");
                    e.day = o.optString("day");
                    e.allDay = o.optBoolean("allDay");
                    e.start = o.optString("start");
                    try { e.color = Color.parseColor(o.optString("color")); } catch (Exception x) { e.color = 0xFF378ADD; }
                    String day = e.day.compareTo(from) < 0 ? from : e.day, last = o.optString("endDay");
                    if (last.compareTo(to) > 0) last = to;
                    for (int n = 0; day.compareTo(last) <= 0 && n < 62; n++, day = addDays(day, 1)) {
                        List<Ev> at = events.get(day);
                        if (at == null) events.put(day, at = new ArrayList<>());
                        at.add(e);
                    }
                }
            } catch (Exception ignored) {
                return;     // 캘린더를 못 읽으면 근무만
            }
            for (List<Ev> at : events.values()) {
                at.sort((a, b) -> a.allDay != b.allDay ? (a.allDay ? -1 : 1) : a.start.compareTo(b.start));
            }
        }

        List<Ev> eventsAt(String day) {
            List<Ev> l = events.get(day);
            return l == null ? new ArrayList<>() : l;
        }
    }

    private static final class Ev {
        String title, day, start;
        boolean allDay;
        int color;
    }

    private static String addDays(String day, int n) {
        try {
            SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT);
            Calendar cal = Calendar.getInstance();
            cal.setTime(f.parse(day));
            cal.add(Calendar.DAY_OF_MONTH, n);
            return f.format(cal.getTime());
        } catch (Exception e) {
            return day;
        }
    }

    private static int weekday(String day) {
        try {
            Calendar cal = Calendar.getInstance();
            cal.setTime(new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).parse(day));
            return cal.get(Calendar.DAY_OF_WEEK) - 1;
        } catch (Exception e) {
            return 0;
        }
    }

    // ==========================================
    // 그리기 (단위는 dp)
    // ==========================================
    static int mix(int c, int to, float f) {
        int r = Math.round(Color.red(c) + (Color.red(to) - Color.red(c)) * f);
        int g = Math.round(Color.green(c) + (Color.green(to) - Color.green(c)) * f);
        int b = Math.round(Color.blue(c) + (Color.blue(to) - Color.blue(c)) * f);
        return Color.rgb(r, g, b);
    }

    private static final class Painter {
        final Canvas cv;
        final float w, h;
        final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);

        Painter(Canvas cv, float w, float h) {
            this.cv = cv;
            this.w = w;
            this.h = h;
        }

        void background() {
            fill.setColor(0xFFFFFFFF);
            cv.drawRoundRect(new RectF(0, 0, w, h), 16, 16, fill);
        }

        float textAt(String s, float x, float y, float size, int color, boolean bold, Paint.Align align) {
            text.setTextSize(size);
            text.setColor(color);
            text.setTypeface(bold ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
            text.setTextAlign(align);
            cv.drawText(s, x, y, text);
            return text.measureText(s);
        }

        String fit(String s, float size, float max) {
            text.setTextSize(size);
            if (text.measureText(s) <= max) return s;
            while (s.length() > 1 && text.measureText(s + "…") > max) s = s.substring(0, s.length() - 1);
            return s + "…";
        }

        /** 근무 배지: 가운데 (cx, cy), 높이 bh */
        void badge(Type t, float cx, float cy, float bh, float maxW, float size) {
            String s = fit(t.code, size, maxW - 6);
            text.setTextSize(size);
            text.setTypeface(Typeface.DEFAULT_BOLD);
            float bw = Math.min(maxW, Math.max(bh * 1.2f, text.measureText(s) + 8));
            fill.setColor(mix(t.color, 0xFFFFFFFF, 0.8f));
            cv.drawRoundRect(new RectF(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), 4, 4, fill);
            Paint.FontMetrics fm = text.getFontMetrics();
            textAt(s, cx, cy - (fm.ascent + fm.descent) / 2, size, mix(t.color, 0xFF000000, 0.5f), true, Paint.Align.CENTER);
        }

        void message(String s) {
            textAt(fit(s, 12, w - 24), w / 2, h / 2 + 4, 12, MUTED, false, Paint.Align.CENTER);
        }

        void stale(String s) {
            textAt(s, w - 10, h - 6, 9, FAINT, false, Paint.Align.RIGHT);
        }

        static final float EV_LINE = 11, EV_GAP = 1;

        /** 칸 안 일정: 남는 높이만큼 한 줄에 하나씩 (왼쪽 캘린더 색 띠 + 이름). 다 못 넣으면 마지막 줄 오른쪽에 +n */
        void eventLines(List<Ev> evs, RectF area) {
            int fit = (int) ((area.height() + EV_GAP) / (EV_LINE + EV_GAP));
            int n = Math.min(evs.size(), fit);
            for (int i = 0; i < n; i++) {
                Ev e = evs.get(i);
                float top = area.top + i * (EV_LINE + EV_GAP);
                RectF r = new RectF(area.left, top, area.right, top + EV_LINE);
                fill.setColor(mix(e.color, 0xFFFFFFFF, 0.85f));
                cv.drawRect(r, fill);
                fill.setColor(e.color);
                cv.drawRect(new RectF(r.left, r.top, r.left + 2, r.bottom), fill);
                int rest = i == n - 1 ? evs.size() - n : 0;
                String more = rest > 0 ? "+" + rest : "";
                float moreW = 0;
                if (rest > 0) {
                    text.setTypeface(Typeface.DEFAULT_BOLD);
                    text.setTextSize(8);
                    moreW = text.measureText(more) + 2;
                }
                float max = r.width() - 4 - moreW;
                if (max >= 6) {
                    text.setTypeface(Typeface.DEFAULT);
                    textAt(fitClip(e.title, 9, max), r.left + 3.5f, r.bottom - 2.5f, 9, TEXT, false, Paint.Align.LEFT);
                }
                if (rest > 0) textAt(more, r.right - 1, r.bottom - 2.5f, 8, MUTED, true, Paint.Align.RIGHT);
            }
        }

        /** 이름을 넣을 자리가 없는 칸: 맨 아래에 일정 색 띠 (3개까지 나눠서) */
        void eventBar(List<Ev> evs, RectF cell) {
            int n = Math.min(3, evs.size());
            float x0 = cell.left + 4, seg = (cell.width() - 8 - (n - 1)) / n;
            for (int i = 0; i < n; i++) {
                fill.setColor(evs.get(i).color);
                float x = x0 + i * (seg + 1);
                cv.drawRect(new RectF(x, cell.bottom - 4, x + seg, cell.bottom - 2), fill);
            }
        }

        /** 줄임표 없이 자름 (칸이 좁아 '…'이 한 글자 자리를 차지하는 게 아까움) */
        String fitClip(String s, float size, float max) {
            text.setTextSize(size);
            while (s.length() > 1 && text.measureText(s) > max) s = s.substring(0, s.length() - 1);
            return s;
        }

        /** 한 달: 제목(달·사람) · 오늘·내일 · 요일 · 날짜마다 근무 배지 */
        void month(Roster r) {
            float pad = 10;
            String[] ym = r.month.split("-");
            int y = Integer.parseInt(ym[0]), mo = Integer.parseInt(ym[1]);
            textAt(fit(mo + "월 근무 · " + r.personName, 13, w * 0.55f), pad, pad + 13, 13, TEXT, true, Paint.Align.LEFT);
            Type t0 = r.at(r.today), t1 = r.at(addDays(r.today, 1));
            String right = "오늘 " + (t0 == null ? "–" : t0.code) + " · 내일 " + (t1 == null ? "–" : t1.code);
            textAt(right, w - pad, pad + 12, 11, t0 == null ? MUTED : mix(t0.color, 0xFF000000, 0.4f), true, Paint.Align.RIGHT);

            Calendar cal = Calendar.getInstance();
            cal.clear();
            cal.set(y, mo - 1, 1);
            int first = cal.get(Calendar.DAY_OF_WEEK) - 1, last = cal.getActualMaximum(Calendar.DAY_OF_MONTH);
            int rows = (first + last + 6) / 7;
            float top = pad + 22, colW = (w - pad * 2) / 7;
            for (int i = 0; i < 7; i++) {
                textAt(String.valueOf(WD.charAt(i)), pad + colW * i + colW / 2, top + 10, 10, i == 0 ? SUN : i == 6 ? SAT : FAINT, false, Paint.Align.CENTER);
            }
            top += 15;
            float cellH = (h - top - pad + 2) / rows, gap = 2;
            boolean roomy = cellH >= 30;
            for (int day = 1; day <= last; day++) {
                int idx = first + day - 1, col = idx % 7, row = idx / 7;
                String key = String.format(Locale.ROOT, "%s-%02d", r.month, day);
                RectF cell = new RectF(pad + colW * col + gap / 2, top + cellH * row + gap / 2, pad + colW * (col + 1) - gap / 2, top + cellH * (row + 1) - gap / 2);
                Type t = r.at(key);
                boolean today = key.equals(r.today);
                int numColor = col == 0 ? SUN : col == 6 ? SAT : MUTED;
                List<Ev> evs = r.eventsAt(key);
                if (roomy) {
                    textAt(String.valueOf(day), cell.centerX(), cell.top + 11, 10, today ? GREEN : numColor, today, Paint.Align.CENTER);
                    float below = cell.top + 15;
                    if (t != null) {
                        // 날짜 바로 아래, 일정이 있든 없든 같은 크기·같은 자리
                        float bh = Math.min(16, cell.height() - 18);
                        float cy = cell.top + 16 + bh / 2;
                        badge(t, cell.centerX(), cy, bh, cell.width() - 2, Math.min(11, bh - 4));
                        below = cy + bh / 2;
                    }
                    if (!evs.isEmpty()) {
                        RectF area = new RectF(cell.left + 2, below + 2, cell.right - 2, cell.bottom - 2);
                        if (area.height() >= EV_LINE) eventLines(evs, area);
                        else eventBar(evs, cell);
                    }
                } else {
                    // 칸이 낮으면: 근무 색을 칸에 깔고 날짜만 (근무 글자는 생략)
                    if (t != null) {
                        fill.setColor(mix(t.color, 0xFFFFFFFF, 0.75f));
                        cv.drawRoundRect(cell, 4, 4, fill);
                    }
                    Paint.FontMetrics fm;
                    text.setTextSize(10);
                    fm = text.getFontMetrics();
                    textAt(String.valueOf(day), cell.centerX(), cell.centerY() - (fm.ascent + fm.descent) / 2, 10,
                            t != null ? mix(t.color, 0xFF000000, 0.5f) : today ? GREEN : numColor, today || t != null, Paint.Align.CENTER);
                    if (!evs.isEmpty()) eventBar(evs, cell);
                }
                if (today) {
                    Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
                    line.setStyle(Paint.Style.STROKE);
                    line.setStrokeWidth(1.6f);
                    line.setColor(GREEN);
                    cv.drawRoundRect(cell, 5, 5, line);
                }
            }
        }

        /** 오늘 일정 한 줄: '● 10:00 병원 ● 19:00 운동 외 1' (자리가 모자라면 '외 n') */
        void todayEvents(List<Ev> evs, String day, float x0, float y, float maxW) {
            float x = x0, right = x0 + maxW;
            for (int i = 0; i < evs.size(); i++) {
                Ev e = evs.get(i);
                String s = (!e.allDay && e.day.equals(day) ? e.start + " " : "") + e.title;
                int left = evs.size() - i - 1;
                text.setTypeface(Typeface.DEFAULT);
                text.setTextSize(10);
                float rest = left > 0 ? text.measureText("외 " + left) + 2 : 0;
                float avail = right - x - 8 - rest;
                if (i > 0 && avail < 30) {
                    textAt("외 " + (evs.size() - i), x, y, 10, FAINT, false, Paint.Align.LEFT);
                    return;
                }
                fill.setColor(e.color);
                cv.drawCircle(x + 3, y - 3.5f, 3, fill);
                String shown = fit(s, 10, Math.max(12, avail));
                x += 8 + textAt(shown, x + 8, y, 10, TEXT, false, Paint.Align.LEFT) + 6;
                if (!shown.equals(s)) {
                    if (left > 0) textAt("외 " + left, x - 4, y, 10, FAINT, false, Paint.Align.LEFT);
                    return;
                }
            }
        }

        /** 작게: 오늘 근무(이름·시간) + 오른쪽에 다음 사흘 */
        void today(Roster r) {
            float pad = 10;
            Type t = r.at(r.today);
            int wd = weekday(r.today);
            String[] p = r.today.split("-");
            String label = "오늘 " + Integer.parseInt(p[1]) + "/" + Integer.parseInt(p[2]) + " (" + WD.charAt(wd) + ")" + (r.personName.isEmpty() ? "" : " · " + r.personName);
            boolean side = w >= 150;
            float leftW = side ? w - pad * 2 - 58 : w - pad * 2;
            float mid = h / 2;
            List<Ev> evs = h >= 60 ? r.eventsAt(r.today) : new ArrayList<>();
            // 위젯이 높으면 오늘 일정을 한 줄에 하나씩 (라벨 14 + 근무 20 + 일정 줄마다 13)
            int lines = (int) ((h - 2 * pad - 36) / 13);
            if (evs.size() >= 2 && lines >= 2) {
                int n = Math.min(evs.size(), lines);
                float top = (h - (36 + n * 13)) / 2;
                textAt(fit(label, 10, leftW), pad, top + 10, 10, MUTED, false, Paint.Align.LEFT);
                if (t == null) {
                    textAt("근무 없음", pad, top + 29, 15, FAINT, false, Paint.Align.LEFT);
                } else {
                    float nw = textAt(fit(t.name, 16, leftW), pad, top + 29, 16, mix(t.color, 0xFF000000, 0.4f), true, Paint.Align.LEFT);
                    if (!t.time.isEmpty() && nw + 6 + 50 <= leftW) textAt(t.time, pad + nw + 6, top + 29, 10, MUTED, false, Paint.Align.LEFT);
                }
                for (int i = 0; i < n; i++) {
                    Ev e = evs.get(i);
                    float y = top + 36 + 13 * i + 10;
                    int rest = i == n - 1 ? evs.size() - n : 0;
                    String more = rest > 0 ? "외 " + rest : "";
                    text.setTypeface(Typeface.DEFAULT);
                    text.setTextSize(10);
                    float moreW = rest > 0 ? text.measureText(more) + 6 : 0;
                    fill.setColor(e.color);
                    cv.drawCircle(pad + 3, y - 3.5f, 3, fill);
                    String s = (!e.allDay && e.day.equals(r.today) ? e.start + " " : "") + e.title;
                    textAt(fit(s, 10, leftW - 8 - moreW), pad + 8, y, 10, TEXT, false, Paint.Align.LEFT);
                    if (rest > 0) textAt(more, pad + leftW, y, 10, FAINT, false, Paint.Align.RIGHT);
                }
                nextDays(r, pad, h / 2, side);
                return;
            }
            boolean withEv = !evs.isEmpty();
            float up = withEv ? 7 : 0;     // 오늘 일정 줄 자리만큼 위로
            textAt(fit(label, 10, leftW), pad, mid - 12 - up, 10, MUTED, false, Paint.Align.LEFT);
            if (t == null) {
                textAt("근무 없음", pad, mid + 6 - up, 15, FAINT, false, Paint.Align.LEFT);
            } else if (withEv) {
                // 근무 시간은 이름 옆으로 (아래 줄은 일정)
                float nw = textAt(fit(t.name, 16, leftW), pad, mid + 7 - up, 16, mix(t.color, 0xFF000000, 0.4f), true, Paint.Align.LEFT);
                if (!t.time.isEmpty() && nw + 6 + 50 <= leftW) textAt(t.time, pad + nw + 6, mid + 7 - up, 10, MUTED, false, Paint.Align.LEFT);
            } else {
                textAt(fit(t.name, 16, leftW), pad, mid + 7, 16, mix(t.color, 0xFF000000, 0.4f), true, Paint.Align.LEFT);
                if (!t.time.isEmpty() && h >= 56) textAt(t.time, pad, mid + 21, 10, MUTED, false, Paint.Align.LEFT);
            }
            if (withEv) todayEvents(evs, r.today, pad, mid + 23 - up, leftW);
            nextDays(r, pad, mid, side);
        }

        /** 작은 위젯 오른쪽: 내일부터 사흘(높이가 낮으면 이틀) 근무 */
        void nextDays(Roster r, float pad, float mid, boolean side) {
            if (!side) return;
            int n = h >= 64 ? 3 : 2;
            float rowH = Math.min(17, (h - 12) / n), y0 = mid - rowH * n / 2;
            for (int i = 1; i <= n; i++) {
                String day = addDays(r.today, i);
                Type nt = r.at(day);
                float cy = y0 + rowH * (i - 1) + rowH / 2;
                textAt(i == 1 ? "내일" : String.valueOf(WD.charAt(weekday(day))), w - pad - 34, cy + 4, 10, FAINT, false, Paint.Align.RIGHT);
                if (nt != null) badge(nt, w - pad - 15, cy, rowH - 3, 30, 10);
                else textAt("–", w - pad - 15, cy + 4, 10, FAINT, false, Paint.Align.CENTER);
            }
        }
    }
}
