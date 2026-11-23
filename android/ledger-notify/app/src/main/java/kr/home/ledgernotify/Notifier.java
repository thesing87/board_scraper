package kr.home.ledgernotify;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONObject;

import java.text.NumberFormat;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 금액 인식 알림: 결제 알림을 가계부 확인 대기함에 넣으면 금액·가게를 휴대폰 알림으로 (설정에서 끔).
 * 인터넷이 안 돼 아직 못 보낸 결제도 알릴 수 있음 ('못 보낸 것도 알림', 처음엔 꺼짐). 같은 결제는 같은 알림 번호라
 * 나중에 보내지면 '못 보냄' 알림이 '넣음' 알림으로 바뀜. 누르면 앱의 가계부 확인 대기함이 열림
 */
final class Notifier {
    static final String CHANNEL = "pay_amount";
    static final String EXTRA_INBOX = "open_inbox";
    private static final String GROUP = "kr.home.ledgernotify.PAY";
    private static final int SUMMARY_ID = 1;
    private static final Pattern AMOUNT = Pattern.compile("(?<![\\d,])(\\d{1,3}(?:,\\d{3})+|\\d+)\\s*원");

    private Notifier() { }

    /** 안드로이드 13 이상은 알림 권한이 있어야 띄울 수 있음 (그 밖에는 앱 알림이 꺼져 있지 않으면) */
    static boolean allowed(Context c) {
        if (Build.VERSION.SDK_INT >= 33 && c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        return nm != null && nm.areNotificationsEnabled();
    }

    /** 확인 대기함에 넣음: item = 서버가 답한 {amount, merchant, card, cancel, category} */
    static void saved(Context c, int id, JSONObject item) {
        if (!new Store(c).alertOn() || item == null) return;
        boolean cancel = item.optBoolean("cancel");
        String merchant = item.optString("merchant", "").trim();
        if ("null".equals(merchant)) merchant = "";
        String title = (cancel ? "취소 −" : "") + won(item.optLong("amount")) + (merchant.isEmpty() ? "" : " · " + merchant);
        List<String> parts = new ArrayList<>();
        String card = clean(item.optString("card", ""));
        if (!card.isEmpty()) parts.add(card);
        parts.add("확인 대기함에 넣음");
        String category = clean(item.optString("category", ""));
        if (!category.isEmpty()) parts.add("분류: " + category);
        show(c, id, title, String.join(" · ", parts));
    }

    /** 금액은 알아봤지만 아직 못 보냄 (인터넷이 안 될 때) */
    static void pending(Context c, int id, String text) {
        Store s = new Store(c);
        if (!s.alertOn() || !s.alertPendingOn()) return;
        Matcher m = AMOUNT.matcher(text == null ? "" : text);
        String amount = m.find() ? m.group(1) + "원" : "결제";
        show(c, id, amount + " 인식 · 아직 못 보냄", "인터넷이 연결되면 확인 대기함으로 보냅니다");
    }

    /** 같은 결제의 알림 번호 (줄에 넣은 시각으로). 요약 알림 번호(1)와 겹치지 않게 */
    static int idFor(long t) {
        int id = (int) (t ^ (t >>> 32)) & 0x7fffffff;
        return id <= SUMMARY_ID ? id + 2 : id;
    }

    private static void show(Context c, int id, String title, String body) {
        if (!allowed(c)) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return;
        ensureChannel(nm);
        nm.notify(id, base(c)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setGroup(GROUP)
                .build());
        // 여러 건이 몰리면 하나로 묶음 ('가계부 결제 3건')
        int count = 0;
        for (android.service.notification.StatusBarNotification n : nm.getActiveNotifications()) {
            if (n.getId() != SUMMARY_ID && GROUP.equals(n.getNotification().getGroup())) count++;
        }
        if (count >= 2) {
            nm.notify(SUMMARY_ID, base(c)
                    .setContentTitle("가계부 결제 " + count + "건")
                    .setContentText("확인 대기함을 확인해 주세요")
                    .setGroup(GROUP)
                    .setGroupSummary(true)
                    .build());
        }
    }

    private static Notification.Builder base(Context c) {
        Intent open = new Intent(c, MainActivity.class)
                .putExtra(EXTRA_INBOX, true)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(c, CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setShowWhen(true);
    }

    private static void ensureChannel(NotificationManager nm) {
        if (nm.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL, "금액 인식 알림", NotificationManager.IMPORTANCE_DEFAULT);
        ch.setDescription("결제를 확인 대기함에 넣으면 금액과 가게를 알려 줘요");
        nm.createNotificationChannel(ch);
    }

    private static String clean(String s) {
        s = s == null ? "" : s.trim();
        return "null".equals(s) ? "" : s;
    }

    static String won(long amount) {
        return NumberFormat.getIntegerInstance(Locale.KOREA).format(amount) + "원";
    }
}
