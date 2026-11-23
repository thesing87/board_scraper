package kr.home.ledgernotify;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 알림 글을 가계부 연결 주소로 보냄. 줄(Store queue)에 넣고 차례로 보내며, 인터넷이 안 되면 RetryJob이 나중에 다시 */
final class Sender {
    private static final ExecutorService ONE = Executors.newSingleThreadExecutor();
    private static final int RETRY_JOB_ID = 7101;

    private Sender() { }

    /** 받은 알림 하나: 결제 알림이고 켜진 앱이면 줄에 넣고 보냄 */
    static void offer(Context c, String pkg, String app, String text) {
        Store s = new Store(c);
        if (!s.enabled() || s.url().isEmpty() || !PayFilter.looksLikePayment(text)) return;
        if (!s.appAllowed(pkg, app) || s.seenRecently(text)) return;
        // 무시할 표현이 있으면 보내지 않음 (휴대폰 밖으로 나가지 않음), 기록에만 남김
        String hit = s.ignoredBy(text);
        if (hit != null) {
            s.log(app, text, "거름 ('" + hit + "') — 휴대폰 밖으로 안 나감", false, true);
            return;
        }
        s.enqueue(app, text);
        flushAsync(c, null);
    }

    /** '시험 보내기': 거르지 않고 바로 줄에 */
    static void sendTest(Context c, String text, Runnable done) {
        new Store(c).enqueue("시험", text);
        flushAsync(c, done);
    }

    static void flushAsync(Context c, Runnable done) {
        Context app = c.getApplicationContext();
        ONE.execute(() -> {
            flush(app);
            if (done != null) done.run();
        });
    }

    /** 줄에 있는 것을 앞에서부터 보냄. 다 보냈으면 true (못 보낸 것이 남으면 다시 시도할 작업을 걸어 둠) */
    static boolean flush(Context c) {
        // 바로 보내기(ONE)와 RetryJob이 겹쳐 같은 알림을 두 번 보내지 않게
        synchronized (FLUSH) {
            return flushLocked(c);
        }
    }

    private static final Object FLUSH = new Object();

    private static boolean flushLocked(Context c) {
        Store s = new Store(c);
        JSONObject item;
        while ((item = s.peek()) != null) {
            String app = item.optString("app"), text = item.optString("text");
            Result r = post(s.url(), text);
            int id = Notifier.idFor(item.optLong("t"));
            if (r.retry) {
                scheduleRetry(c);
                s.log(app, text, "보내지 못함 — 나중에 다시 (" + r.message + ")", false);
                // 금액은 알아봤지만 못 보냄 ('못 보낸 것도 알림'을 켰을 때, 결제마다 한 번)
                for (JSONObject w : s.takeUnwarned()) Notifier.pending(c, Notifier.idFor(w.optLong("t")), w.optString("text"));
                return false;
            }
            s.dropFirst();
            s.log(app, text, r.message, r.ok);
            if (r.item != null) Notifier.saved(c, id, r.item);
        }
        return true;
    }

    static final class Result {
        final boolean ok, retry;
        final String message;
        final JSONObject item;   // 확인 대기함에 넣은 내용 (서버가 답했을 때만: 금액·가게·카드·취소·분류)
        Result(boolean ok, boolean retry, String message) { this(ok, retry, message, null); }
        Result(boolean ok, boolean retry, String message, JSONObject item) { this.ok = ok; this.retry = retry; this.message = message; this.item = item; }
    }

    static Result post(String url, String text) {
        if (url.isEmpty()) return new Result(false, false, "연결 주소가 없음");
        HttpURLConnection con = null;
        try {
            con = (HttpURLConnection) new URL(url).openConnection();
            con.setConnectTimeout(10000);
            con.setReadTimeout(15000);
            con.setRequestMethod("POST");
            con.setDoOutput(true);
            con.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
            byte[] body = text.getBytes(StandardCharsets.UTF_8);
            con.setFixedLengthStreamingMode(body.length);
            try (OutputStream o = con.getOutputStream()) { o.write(body); }
            int code = con.getResponseCode();
            String reply = read(code < 400 ? con.getInputStream() : con.getErrorStream());
            if (code == 200) {
                JSONObject json = new JSONObject(reply);
                String result = json.optString("result");
                switch (result) {
                    case "saved": {
                        JSONObject item = json.optJSONObject("item");
                        String what = item == null ? "" : " (" + (item.optBoolean("cancel") ? "취소 " : "") + Notifier.won(item.optLong("amount")) + ")";
                        return new Result(true, false, "확인 대기함에 넣음" + what, item);
                    }
                    case "duplicate": return new Result(true, false, "같은 알림이 이미 있어 넘김");
                    case "ignored": return new Result(true, false, "결제 알림이 아니라고 서버가 넘김");
                    case "too_many": return new Result(false, false, "한 시간에 너무 많이 보내 넘김");
                    default: return new Result(true, false, "보냄");
                }
            }
            if (code == 404) return new Result(false, false, "연결 주소가 맞지 않음 (가계부에서 새로 만들었나요?)");
            if (code == 413) return new Result(false, false, "알림 글이 너무 김");
            if (code == 429) return new Result(false, true, "서버가 잠시 막음");
            if (code >= 500) return new Result(false, true, "서버 오류 " + code);
            return new Result(false, false, "서버가 거절함 " + code);
        } catch (Exception e) {
            return new Result(false, true, "연결 안 됨");
        } finally {
            if (con != null) con.disconnect();
        }
    }

    private static String read(InputStream in) throws java.io.IOException {
        if (in == null) return "";
        try (InputStream i = in) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[2048];
            int n;
            while ((n = i.read(buf)) > 0 && b.size() < 65536) b.write(buf, 0, n);
            return b.toString("UTF-8");
        }
    }

    private static void scheduleRetry(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (js == null || js.getPendingJob(RETRY_JOB_ID) != null) return;
        js.schedule(new JobInfo.Builder(RETRY_JOB_ID, new ComponentName(c, RetryJob.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setMinimumLatency(30_000)
                .setBackoffCriteria(60_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .setPersisted(true)
                .build());
    }
}
