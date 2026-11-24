package kr.home.ledgernotify;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import org.json.JSONObject;

import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * 근무표·가계부 변경 알림 (FCM): 누가 근무표나 가계부 기록을 고치면 서버(duty_push.py·ledger_push.py)가 고친 사람을 뺀 모두에게 보냄.
 * 이 휴대폰의 FCM 토큰을 가계부 로그인과 함께, 어떤 알림을 받을지(duty·ledger)와 함께 서버에 등록해 둠 (로그아웃하면 서버에서 함께 지워짐).
 * 앱이 뒤에 있을 때는 시스템이 알림을 띄우고(채널 duty_change·ledger_change), 앱이 앞에 있을 때는 여기서 띄움.
 * 누르면 근무표 탭·가계부 탭
 */
public class DutyPush extends FirebaseMessagingService {
    static final String CHANNEL = "duty_change", LEDGER_CHANNEL = "ledger_change";
    static final String KIND_DUTY = "duty", KIND_LEDGER = "ledger";
    /** 알림 데이터 (시스템이 띄운 알림을 누르면 MainActivity에 그대로 extras로 옴) */
    static final String EXTRA_KIND = "kind";
    private static final long RESYNC_MS = 24L * 3600 * 1000;

    @Override
    public void onNewToken(String token) {
        Store s = new Store(this);
        s.setPushSent("");
        if (s.anyPushOn()) new Thread(() -> post(this, "push-token", token)).start();
    }

    @Override
    public void onMessageReceived(RemoteMessage m) {
        boolean ledger = KIND_LEDGER.equals(m.getData().get(EXTRA_KIND));
        Store s = new Store(this);
        if (ledger ? !s.ledgerPushOn() : !s.dutyPushOn()) return;
        RemoteMessage.Notification n = m.getNotification();
        if (n == null || !Notifier.allowed(this)) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        ensureChannel(this);
        Intent open = new Intent(this, MainActivity.class).putExtra(MainActivity.EXTRA_TAB, ledger ? MainActivity.TAB_LEDGER : MainActivity.TAB_DUTY)
                .putExtra(EXTRA_KIND, ledger ? KIND_LEDGER : KIND_DUTY)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        int id = (int) (System.currentTimeMillis() & 0x7fffffff);
        PendingIntent pi = PendingIntent.getActivity(this, id, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        String body = n.getBody() == null ? "" : n.getBody();
        nm.notify(ledger ? KIND_LEDGER : KIND_DUTY, id, new Notification.Builder(this, ledger ? LEDGER_CHANNEL : CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(n.getTitle())
                .setContentText(body.replace('\n', ' '))
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setShowWhen(true)
                .build());
        if (!ledger) DutyWidgets.refreshAll(this);
    }

    /** 알림 채널 (앱을 켤 때 만들어 둠: 앱이 뒤에 있을 때 시스템이 이 채널로 띄움) */
    static void ensureChannel(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return;
        if (nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "근무표 변경 알림", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("다른 사람이 근무표를 고치면 알려 줘요");
            nm.createNotificationChannel(ch);
        }
        if (nm.getNotificationChannel(LEDGER_CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(LEDGER_CHANNEL, "가계부 변경 알림", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("다른 사람이 가계부에 기록을 넣거나 고치거나 지우면 알려 줘요");
            nm.createNotificationChannel(ch);
        }
    }

    /** Firebase 설정(google-services.json)을 넣고 빌드했는지 */
    static boolean available(Context c) {
        try {
            return !FirebaseApp.getApps(c).isEmpty() || FirebaseApp.initializeApp(c) != null;
        } catch (Exception e) {
            return false;
        }
    }

    /** 앱을 켤 때·로그인한 뒤: 켜져 있으면 토큰을 서버에 등록 (같은 로그인·토큰이면 하루에 한 번만) */
    static void sync(Context c) {
        Context app = c.getApplicationContext();
        Store s = new Store(app);
        if (!s.anyPushOn() || DutyWidgets.cookie(app) == null || !available(app)) return;
        FirebaseMessaging.getInstance().getToken().addOnSuccessListener(token -> {
            String key = token + "|" + Integer.toHexString(String.valueOf(DutyWidgets.cookie(app)).hashCode())
                    + "|" + s.dutyPushOn() + "|" + s.ledgerPushOn();
            if (key.equals(s.pushSent()) && System.currentTimeMillis() - s.pushSentAt() < RESYNC_MS) return;
            new Thread(() -> {
                if (post(app, "push-token", token)) s.setPushSent(key);
            }).start();
        });
    }

    /** 설정에서 근무표·가계부 알림을 켜거나 끔: 하나라도 켜져 있으면 받을 알림을 서버에 다시 알리고,
     *  둘 다 끄면 서버에서 이 휴대폰 토큰을 지움 (끈 동안은 알림이 안 옴) */
    static void changed(Context c) {
        Context app = c.getApplicationContext();
        Store s = new Store(app);
        s.setPushSent("");
        if (s.anyPushOn()) {
            sync(app);
            return;
        }
        if (!available(app)) return;
        FirebaseMessaging.getInstance().getToken().addOnSuccessListener(token ->
                new Thread(() -> post(app, "push-token-delete", token)).start());
    }

    /** /api/ledger/duty {action, token, duty, ledger}. 서버가 받았으면 true */
    private static boolean post(Context c, String action, String token) {
        String origin = Store.origin(new Store(c).site());
        String cookie = DutyWidgets.cookie(c);
        if (origin.isEmpty() || cookie == null || token == null) return false;
        HttpURLConnection con = null;
        try {
            con = (HttpURLConnection) new URL(origin + "/api/ledger/duty").openConnection();
            con.setRequestMethod("POST");
            con.setDoOutput(true);
            con.setConnectTimeout(8000);
            con.setReadTimeout(10000);
            con.setRequestProperty("Content-Type", "application/json");
            con.setRequestProperty("Cookie", cookie);
            Store s = new Store(c);
            byte[] body = new JSONObject().put("action", action).put("token", token)
                    .put("duty", s.dutyPushOn()).put("ledger", s.ledgerPushOn()).toString().getBytes(StandardCharsets.UTF_8);
            con.setFixedLengthStreamingMode(body.length);
            con.getOutputStream().write(body);
            return con.getResponseCode() == 200;
        } catch (Exception e) {
            return false;
        } finally {
            if (con != null) con.disconnect();
        }
    }
}
