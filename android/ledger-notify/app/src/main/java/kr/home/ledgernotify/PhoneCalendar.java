package kr.home.ledgernotify;

import android.Manifest;
import android.content.ContentUris;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.provider.CalendarContract;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;

/**
 * 휴대폰 캘린더 읽기 (1.16부터): 휴대폰에 연결된 구글 계정 등의 캘린더 일정을 근무표 달력에 함께 보여 줌.
 * 구글 로그인 없이 휴대폰이 맞춰 둔 캘린더(CalendarContract)를 읽기만 하고, 서버로 보내지 않음 (이 휴대폰에서만 보임).
 */
final class PhoneCalendar {
    private PhoneCalendar() {}

    static boolean allowed(Context c) {
        return c.checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED;
    }

    private static String hex(int color) {
        return String.format(Locale.ROOT, "#%06X", color & 0xFFFFFF);
    }

    /** 휴대폰의 캘린더 목록 [{id, name, account, color, shown}] (휴대폰 캘린더 앱에서 숨긴 것은 뺌) */
    static JSONArray calendars(Context c, Set<String> hidden) throws JSONException {
        JSONArray out = new JSONArray();
        if (!allowed(c)) return out;
        String[] cols = {CalendarContract.Calendars._ID, CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
                CalendarContract.Calendars.ACCOUNT_NAME, CalendarContract.Calendars.CALENDAR_COLOR};
        try (Cursor q = c.getContentResolver().query(CalendarContract.Calendars.CONTENT_URI, cols,
                CalendarContract.Calendars.VISIBLE + "=1", null,
                CalendarContract.Calendars.ACCOUNT_NAME + "," + CalendarContract.Calendars.CALENDAR_DISPLAY_NAME)) {
            while (q != null && q.moveToNext()) {
                String id = String.valueOf(q.getLong(0));
                out.put(new JSONObject().put("id", id).put("name", q.getString(1)).put("account", q.getString(2))
                        .put("color", hex(q.getInt(3))).put("shown", !hidden.contains(id)));
            }
        } catch (SecurityException e) {
            // 권한을 막 끔
        }
        return out;
    }

    /**
     * from~to(yyyy-MM-dd, 끝 날 포함) 사이의 일정 [{day, endDay, allDay, start, end, title, color}].
     * 반복 일정은 날마다 따로 (Instances). 여러 날 일정은 day~endDay (페이지가 날마다 나눠 그림)
     */
    static JSONArray events(Context c, String from, String to, Set<String> hidden) throws JSONException {
        JSONArray out = new JSONArray();
        if (!allowed(c)) return out;
        SimpleDateFormat local = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT);
        SimpleDateFormat utc = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT);
        utc.setTimeZone(TimeZone.getTimeZone("UTC"));
        SimpleDateFormat hm = new SimpleDateFormat("HH:mm", Locale.ROOT);
        long begin, end;
        try {
            // 종일 일정은 UTC 자정 기준이라 앞뒤로 하루씩 넉넉히 (페이지가 그 달만 골라 씀)
            begin = local.parse(from).getTime() - 86400000L;
            end = local.parse(to).getTime() + 2 * 86400000L;
        } catch (java.text.ParseException | NullPointerException e) {
            return out;
        }
        Uri.Builder b = CalendarContract.Instances.CONTENT_URI.buildUpon();
        ContentUris.appendId(b, begin);
        ContentUris.appendId(b, end);
        String[] cols = {CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN, CalendarContract.Instances.END,
                CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.CALENDAR_ID, CalendarContract.Instances.DISPLAY_COLOR};
        try (Cursor q = c.getContentResolver().query(b.build(), cols,
                CalendarContract.Instances.VISIBLE + "=1 AND " + CalendarContract.Instances.STATUS + "!=" + CalendarContract.Instances.STATUS_CANCELED,
                null, CalendarContract.Instances.BEGIN)) {
            while (q != null && q.moveToNext()) {
                if (hidden.contains(String.valueOf(q.getLong(4)))) continue;
                long s = q.getLong(1), e = q.getLong(2);
                boolean allDay = q.getInt(3) == 1;
                SimpleDateFormat f = allDay ? utc : local;
                // 끝 시각은 그 순간을 빼고 (종일 일정은 다음 날 0시가 끝, 자정에 끝나는 일정도 그 전날까지)
                long last = e > s ? e - 1 : s;
                String title = q.getString(0);
                JSONObject o = new JSONObject()
                        .put("day", f.format(new Date(s)))
                        .put("endDay", f.format(new Date(last)))
                        .put("allDay", allDay)
                        .put("title", title == null || title.trim().isEmpty() ? "(제목 없음)" : title.trim())
                        .put("color", hex(q.getInt(5)));
                if (!allDay) o.put("start", hm.format(new Date(s))).put("end", hm.format(new Date(e)));
                out.put(o);
            }
        } catch (SecurityException e) {
            // 권한을 막 끔
        }
        return out;
    }
}
