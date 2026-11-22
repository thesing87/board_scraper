package kr.home.ledgernotify;

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
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 새 버전 자동 업데이트: 가계부에 관리자가 올린 앱(연결 주소/app)을 확인해 지금보다 새것이면 받아(sha256 확인) 설치.
 * 설치는 PackageInstaller로 — 안드로이드 12부터는 앱이 자기 자신을 고치는 것이라 묻지 않고 설치될 수 있고,
 * 그 밖에는 '업데이트' 확인 창이 한 번 뜸(InstallReceiver). 확인 창에서 취소하면 하루 동안 자동으로는 다시 묻지 않음
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
        String base = s.url();
        if (base.isEmpty()) {
            l.onStatus("연결 주소를 넣으면 새 버전을 확인해요", false);
            return;
        }
        l.onStatus("새 버전 확인 중…", false);
        JSONObject reply = new JSONObject(get(base + "/app"));
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
            download(base + "/app.apk", apk, app.optLong("size"));
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

    private static void install(Context c, File apk) throws Exception {
        PackageInstaller pi = c.getPackageManager().getPackageInstaller();
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
    private static String get(String url) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
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

    private static void download(String url, File to, long size) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
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
