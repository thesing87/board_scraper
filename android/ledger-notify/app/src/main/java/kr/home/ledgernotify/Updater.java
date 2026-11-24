package kr.home.ledgernotify;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.ref.WeakReference;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 새 버전 자동 업데이트: 가계부에 관리자가 올린 앱(연결 주소/app)을 확인해 지금보다 새것이면 받아(sha256 확인) 설치.
 * 설치는 PackageInstaller로 — 안드로이드 12부터는 앱이 자기 자신을 고치는 것이라 묻지 않고 설치될 수 있고,
 * 그 밖에는 '업데이트' 확인 창이 한 번 뜸(InstallReceiver → confirm, 보이는 앱 화면 안에서). 확인 창에서 취소하면
 * 하루 동안 자동으로는 다시 묻지 않음 — 뜨자마자(3초 안) 닫힌 것은 취소로 치지 않고 다시 띄움 (2번까지)
 */
final class Updater {
    interface Listener {
        /** 상태 글 (UI 스레드가 아닐 수 있음). needPermission: '이 출처 허용'을 켜야 설치 가능 */
        void onStatus(String text, boolean needPermission);
    }

    private static final ExecutorService ONE = Executors.newSingleThreadExecutor();
    private static final AtomicBoolean RUNNING = new AtomicBoolean(false);
    static final long DECLINE_WAIT_MS = 24 * 60 * 60 * 1000L;

    private Updater() { }

    private static final long AUTO_CHECK_MS = 10 * 60 * 1000L;
    /** 연결 전이고 가계부에 로그인하지 않아 확인하지 못함 (로그인하면 바로 다시 확인) */
    static final String NEED_LOGIN = "가계부에 로그인하면 새 버전을 확인해요";
    private static long lastAuto;

    /** 앱을 열 때 자동 확인할 차례인지 (10분에 한 번 — 확인 창을 닫고 돌아왔을 때 또 묻지 않게). force: 설치 허용을 켜고 돌아온 때 */
    static synchronized boolean autoDue(boolean force) {
        long now = System.currentTimeMillis();
        if (!force && now - lastAuto < AUTO_CHECK_MS) return false;
        lastAuto = now;
        return true;
    }

    static long ownVersion(Context c) {
        try {
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
        } catch (PackageManager.NameNotFoundException e) {
            return 0;
        }
    }

    static String ownVersionName(Context c) {
        try {
            return c.getPackageManager().getPackageInfo(c.getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    /** auto: 앱을 열 때 (확인 창을 하루 안에 취소했으면 받기만 하고 설치는 묻지 않음) */
    static void check(Context ctx, boolean auto, Listener l) {
        Context c = ctx.getApplicationContext();
        if (!RUNNING.compareAndSet(false, true)) return;
        ONE.execute(() -> {
            try {
                run(c, auto, l);
            } catch (Exception e) {
                l.onStatus("새 버전을 확인하지 못했어요 (연결 안 됨)", false);
            } finally {
                RUNNING.set(false);
            }
        });
    }

    private static void run(Context c, boolean auto, Listener l) throws Exception {
        Store s = new Store(c);
        // 연결 주소가 있으면 그 키로, 없으면 앱 안 가계부 로그인(쿠키)으로 확인
        String infoUrl, apkUrl, cookie = null;
        String hook = s.url();
        if (!hook.isEmpty()) {
            infoUrl = hook + "/app";
            apkUrl = hook + "/app.apk";
        } else {
            String origin = Store.origin(s.site());
            if (origin.isEmpty()) {
                l.onStatus("가계부 주소를 넣으면 새 버전을 확인해요", false);
                return;
            }
            cookie = android.webkit.CookieManager.getInstance().getCookie(origin + "/api/ledger/");
            if (cookie == null || !cookie.contains("ledger_session=")) {
                l.onStatus(NEED_LOGIN, false);
                return;
            }
            infoUrl = origin + "/api/ledger/app";
            apkUrl = origin + "/api/ledger/app.apk";
        }
        l.onStatus("새 버전 확인 중…", false);
        JSONObject reply = new JSONObject(get(infoUrl, cookie));
        JSONObject app = reply.optJSONObject("app");
        long own = ownVersion(c);
        if (app == null || app.optLong("versionCode") <= own) {
            l.onStatus("최신 버전이에요", false);
            return;
        }
        String name = app.optString("versionName"), sha = app.optString("sha256");
        File apk = new File(c.getCacheDir(), "update.apk");
        if (!(apk.isFile() && sha.equals(sha256(apk)))) {
            l.onStatus("새 버전 " + name + " 받는 중…", false);
            download(apkUrl, apk, app.optLong("size"), cookie);
            if (!sha.equals(sha256(apk))) {
                apk.delete();
                l.onStatus("새 버전 " + name + "을 받았는데 파일이 맞지 않아요. 다시 시도해 주세요", false);
                return;
            }
        }
        if (!c.getPackageManager().canRequestPackageInstalls()) {
            l.onStatus("새 버전 " + name + "이 있어요. 설치하려면 아래에서 '이 앱의 설치 허용'을 켜 주세요", true);
            return;
        }
        if (auto && System.currentTimeMillis() - s.updateDeclinedAt() < DECLINE_WAIT_MS) {
            l.onStatus("새 버전 " + name + "이 있어요 — '새 버전 확인'을 누르면 설치해요", false);
            return;
        }
        l.onStatus("새 버전 " + name + " 설치 중… (앱이 잠깐 닫혀요)", false);
        install(c, apk);
    }

    // ---------- 확인 창 (모두 UI 스레드에서: 화면 onResume·onPause, InstallReceiver.onReceive)
    /** 확인 창을 띄울 수 있는 앱 화면 (MainActivity·SettingsActivity) */
    interface Host {
        void checkUpdate(boolean auto);
    }

    /** 확인 창이 뜨고 이 안에 닫히면 사람이 취소한 게 아니라 저절로 닫힌 것으로 봄 */
    private static final long QUICK_CLOSE_MS = 3000;
    /** 저절로 닫히면 바로 다시 띄우는 횟수 (계속 닫히면 그만 — '새 버전 확인'을 눌러야 함) */
    private static final int QUICK_RETRIES = 2;
    private static WeakReference<Activity> front = new WeakReference<>(null);
    private static Intent pendingConfirm;
    private static long confirmShownAt;
    private static int quickCloses;
    private static boolean retryOnResume;

    /** 화면 onResume 맨 앞에서: 기다리던 확인 창을 띄우거나, 저절로 닫힌 뒤면 곧바로 다시 확인하게 함 */
    static void resumed(Activity a) {
        front = new WeakReference<>(a);
        if (pendingConfirm != null) {
            Intent i = pendingConfirm;
            pendingConfirm = null;
            showConfirm(a, i);
        } else if (retryOnResume) {
            retryOnResume = false;
            synchronized (Updater.class) { lastAuto = 0; }
        }
    }

    static void paused(Activity a) {
        if (front.get() == a) front = new WeakReference<>(null);
    }

    /**
     * 시스템의 '업데이트' 확인 창. 앱 밖(새 작업)으로 띄우면 앱이 막 켜지는 중에 앱 화면이 그 위로 올라와
     * 창이 저절로 닫히곤 해서, 보이는 앱 화면 안에서 띄움. 앱 화면이 없으면 다음에 앱을 열 때 띄움
     */
    static void confirm(Context c, Intent i) {
        Activity a = front.get();
        if (a == null || a.isFinishing()) {
            pendingConfirm = i;
            return;
        }
        showConfirm(a, i);
    }

    private static void showConfirm(Activity a, Intent i) {
        try {
            a.startActivity(i);
            confirmShownAt = System.currentTimeMillis();
        } catch (RuntimeException e) {
            new Store(a).setUpdateMessage("업데이트 확인 창을 열지 못했어요 — '새 버전 확인'을 다시 눌러 주세요");
        }
    }

    /** 확인 창이 취소로 끝남: 사람이 누른 취소면 하루 동안 묻지 않고, 저절로 닫혔으면 다시 띄움 */
    static void aborted(Store s) {
        long shown = confirmShownAt;
        confirmShownAt = 0;
        boolean quick = shown > 0 && System.currentTimeMillis() - shown < QUICK_CLOSE_MS;
        if (!quick) {
            s.setUpdateDeclinedAt(System.currentTimeMillis());
            s.setUpdateMessage("업데이트를 취소했어요 — 하루 동안은 자동으로 묻지 않아요");
            return;
        }
        if (quickCloses >= QUICK_RETRIES) {
            s.setUpdateMessage("업데이트 창이 자꾸 닫혀요 — '새 버전 확인'을 눌러 주세요");
            return;
        }
        quickCloses++;
        s.setUpdateMessage("");
        Activity a = front.get();
        if (a instanceof Host && !a.isFinishing()) {
            synchronized (Updater.class) { lastAuto = System.currentTimeMillis(); }
            ((Host) a).checkUpdate(true);
        } else {
            retryOnResume = true;   // 앱 화면으로 돌아오면 다시 확인
        }
    }

    private static void install(Context c, File apk) throws Exception {
        PackageInstaller pi = c.getPackageManager().getPackageInstaller();
        // 저절로 닫히거나 앱이 꺼져 끝나지 않은 예전 설치는 치움
        for (PackageInstaller.SessionInfo old : pi.getMySessions()) {
            try { pi.abandonSession(old.getSessionId()); } catch (RuntimeException ignored) { }
        }
        PackageInstaller.SessionParams p = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        p.setAppPackageName(c.getPackageName());
        p.setSize(apk.length());
        if (Build.VERSION.SDK_INT >= 31) p.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
        int id = pi.createSession(p);
        try (PackageInstaller.Session session = pi.openSession(id)) {
            try (InputStream in = new FileInputStream(apk); OutputStream out = session.openWrite("update.apk", 0, apk.length())) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                session.fsync(out);
            }
            int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
            PendingIntent done = PendingIntent.getBroadcast(c, id, new Intent(c, InstallReceiver.class), flags);
            session.commit(done.getIntentSender());
        }
    }

    // ---------- 받기
    private static String get(String url, String cookie) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        if (cookie != null) con.setRequestProperty("Cookie", cookie);
        try {
            con.setConnectTimeout(10000);
            con.setReadTimeout(15000);
            if (con.getResponseCode() != 200) throw new java.io.IOException("HTTP " + con.getResponseCode());
            try (InputStream in = con.getInputStream()) {
                ByteArrayOutputStream b = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0 && b.size() < 65536) b.write(buf, 0, n);
                return b.toString("UTF-8");
            }
        } finally {
            con.disconnect();
        }
    }

    private static void download(String url, File to, long size, String cookie) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        if (cookie != null) con.setRequestProperty("Cookie", cookie);
        File tmp = new File(to.getPath() + ".part");
        try {
            con.setConnectTimeout(10000);
            con.setReadTimeout(30000);
            if (con.getResponseCode() != 200) throw new java.io.IOException("HTTP " + con.getResponseCode());
            long got = 0;
            try (InputStream in = con.getInputStream(); OutputStream out = new FileOutputStream(tmp)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    got += n;
                    if (got > 60L * 1024 * 1024) throw new java.io.IOException("too big");
                }
            }
            if (size > 0 && got != size) throw new java.io.IOException("size");
            if (!tmp.renameTo(to)) {
                to.delete();
                if (!tmp.renameTo(to)) throw new java.io.IOException("rename");
            }
        } finally {
            con.disconnect();
            tmp.delete();
        }
    }

    static String sha256(File f) {
        try (InputStream in = new FileInputStream(f)) {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
            StringBuilder sb = new StringBuilder();
            for (byte b : md.digest()) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }
}
