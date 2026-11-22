package kr.home.ledgernotify;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

/**
 * 휴대폰에 뜨는 알림을 받아 결제 알림이면 Sender로 넘김.
 * 글 = 제목(카드사·보낸 사람) + 본문(긴 본문이 있으면 그것). 문자 앱이 여러 문자를 한 알림으로 묶으면 줄마다 따로
 */
public class NotifyListener extends NotificationListenerService {
    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            handle(sbn);
        } catch (RuntimeException ignored) {
            // 알림 하나 때문에 서비스가 죽지 않게
        }
    }

    private void handle(StatusBarNotification sbn) {
        String pkg = sbn.getPackageName();
        if (getPackageName().equals(pkg)) return;
        Notification n = sbn.getNotification();
        if (n == null || (n.flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;
        Bundle e = n.extras;
        if (e == null) return;
        String title = str(e.getCharSequence(Notification.EXTRA_TITLE));
        String app = label(pkg);
        CharSequence[] lines = e.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
        if (lines != null && lines.length > 1) {
            for (CharSequence line : lines) Sender.offer(this, pkg, app, join(title, str(line)));
            return;
        }
        String big = str(e.getCharSequence(Notification.EXTRA_BIG_TEXT));
        String body = big.isEmpty() ? str(e.getCharSequence(Notification.EXTRA_TEXT)) : big;
        Sender.offer(this, pkg, app, join(title, body));
    }

    private static String join(String title, String body) {
        if (title.isEmpty() || body.contains(title)) return body.trim();
        return (title + "\n" + body).trim();
    }

    private static String str(CharSequence s) {
        return s == null ? "" : s.toString().trim();
    }

    private String label(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            return pm.getApplicationLabel(ai).toString();
        } catch (PackageManager.NameNotFoundException e) {
            return pkg;
        }
    }
}
