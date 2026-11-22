package kr.home.ledgernotify;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ComponentName;
import android.content.Intent;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;

/** 설정 화면: 권한 상태·연결 주소·시험 보내기·앱별 끄기·최근 보낸 알림 */
public class MainActivity extends Activity {
    private static final String HOOK_PATH = "/api/ledger/hook/";

    private Store store;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable tick = new Runnable() {
        @Override public void run() { refresh(); ui.postDelayed(this, 2000); }
    };

    private TextView accessState, batteryState, waitState, urlState, updateState;
    private Button accessBtn, restrictBtn, batteryBtn, retryBtn, installAllowBtn;
    private String updateText = "";
    private boolean updateNeedsPermission;
    private EditText urlInput;
    private Switch enabledSwitch;
    private LinearLayout appsBox, logBox;
    private String shownLogs = "", shownApps = "";

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        store = new Store(this);
        setContentView(build());
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (hasAccess()) NotificationListenerService.requestRebind(new ComponentName(this, NotifyListener.class));
        urlInput.setText(store.url());
        enabledSwitch.setChecked(store.enabled());
        shownLogs = shownApps = "";
        ui.post(tick);
        // 앱을 열면 새 버전 확인 (10분에 한 번 — 확인 창을 닫고 돌아왔을 때 또 묻지 않게).
        // '이 앱의 설치 허용'을 켜러 갔다 돌아온 때는 바로 이어서 설치
        long now = System.currentTimeMillis();
        if (updateNeedsPermission || now - lastAutoCheck > AUTO_CHECK_MS) {
            lastAutoCheck = now;
            checkUpdate(true);
        }
    }

    private static final long AUTO_CHECK_MS = 10 * 60 * 1000L;
    private static long lastAutoCheck;

    private void checkUpdate(boolean auto) {
        Updater.check(this, auto, (text, needPermission) -> ui.post(() -> {
            updateText = text;
            updateNeedsPermission = needPermission;
            refresh();
        }));
    }

    @Override
    protected void onPause() {
        super.onPause();
        ui.removeCallbacks(tick);
    }

    // ==========================================
    // 화면 만들기
    // ==========================================
    private View build() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(16), dp(16), dp(24));

        TextView title = text("가계부 알림", 22, R.color.text);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        root.addView(title);
        root.addView(text("카드 결제 알림을 가계부의 확인 대기함으로 보내요. 결제 알림처럼 보이는 글만 보내고, 다른 알림은 휴대폰 밖으로 나가지 않아요.", 13, R.color.muted), gap(4));

        // ---- 앱 버전·업데이트
        LinearLayout ver = card(root, "앱 버전 " + Updater.ownVersionName(this));
        updateState = text("", 13, R.color.muted);
        ver.addView(updateState);
        LinearLayout vrow = new LinearLayout(this);
        vrow.addView(button("새 버전 확인", v -> checkUpdate(false)), weight());
        installAllowBtn = button("이 앱의 설치 허용", v -> startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:" + getPackageName()))));
        vrow.addView(installAllowBtn, weight());
        ver.addView(vrow, gap(6));

        // ---- 1. 권한
        LinearLayout perm = card(root, "1. 알림 읽기 권한");
        accessState = text("", 14, R.color.text);
        perm.addView(accessState);
        accessBtn = button("알림 읽기 권한 열기", v -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        perm.addView(accessBtn, gap(8));
        perm.addView(text("목록에서 '가계부 알림'이 회색이라 켤 수 없으면: 아래 '앱 정보 열기' → 오른쪽 위 ⋮ → '제한된 설정 허용' 뒤 다시 켜세요.", 12, R.color.muted), gap(8));
        restrictBtn = button("앱 정보 열기", v -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName()))));
        perm.addView(restrictBtn, gap(6));
        batteryState = text("", 14, R.color.text);
        perm.addView(batteryState, gap(14));
        batteryBtn = button("배터리 사용 '제한 없음'으로", v -> {
            Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getPackageName()));
            try { startActivity(i); } catch (RuntimeException e) { startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
        });
        perm.addView(batteryBtn, gap(8));

        // ---- 2. 연결 주소
        LinearLayout link = card(root, "2. 연결 주소");
        link.addView(text("가계부 → '결제 알림 자동 기록' → '연결 주소 만들기'로 받은 주소를 붙여 넣으세요.", 12, R.color.muted));
        urlInput = new EditText(this);
        urlInput.setHint("https://…/api/ledger/hook/…");
        urlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        urlInput.setSingleLine(true);
        urlInput.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        link.addView(urlInput, gap(6));
        LinearLayout row = new LinearLayout(this);
        row.addView(button("붙여넣기", v -> paste()), weight());
        row.addView(button("저장", v -> saveUrl()), weight());
        link.addView(row, gap(4));
        urlState = text("", 12, R.color.muted);
        link.addView(urlState, gap(4));
        enabledSwitch = new Switch(this);
        enabledSwitch.setText("결제 알림 보내기");
        enabledSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        enabledSwitch.setOnCheckedChangeListener((s, on) -> store.setEnabled(on));
        link.addView(enabledSwitch, gap(12));
        link.addView(button("시험 알림 보내기", v -> sendTest()), gap(10));
        waitState = text("", 13, R.color.muted);
        link.addView(waitState, gap(8));
        retryBtn = button("지금 다시 보내기", v -> Sender.flushAsync(this, () -> ui.post(this::refresh)));
        link.addView(retryBtn, gap(4));

        // ---- 3. 앱
        LinearLayout apps = card(root, "3. 결제 알림을 보낸 앱");
        apps.addView(text("결제 알림처럼 보이는 글을 보낸 앱이 여기 쌓여요. 체크를 끄면 그 앱 알림은 보내지 않아요.", 12, R.color.muted));
        appsBox = new LinearLayout(this);
        appsBox.setOrientation(LinearLayout.VERTICAL);
        apps.addView(appsBox, gap(6));

        // ---- 4. 기록
        LinearLayout logs = card(root, "최근 보낸 알림");
        logBox = new LinearLayout(this);
        logBox.setOrientation(LinearLayout.VERTICAL);
        logs.addView(logBox);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        return sv;
    }

    // ==========================================
    // 상태 보이기 (2초마다)
    // ==========================================
    private void refresh() {
        boolean access = hasAccess();
        accessState.setText(access ? "✓ 알림 읽기 권한이 켜져 있어요" : "✗ 알림 읽기 권한이 꺼져 있어요 — 켜야 알림을 받아요");
        accessState.setTextColor(getColor(access ? R.color.green : R.color.bad));
        accessBtn.setVisibility(access ? View.GONE : View.VISIBLE);
        restrictBtn.setVisibility(access ? View.GONE : View.VISIBLE);
        PowerManager pm = getSystemService(PowerManager.class);
        boolean battery = pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
        batteryState.setText(battery ? "✓ 배터리 사용 제한 없음" : "배터리 절약 때문에 앱이 멈출 수 있어요");
        batteryState.setTextColor(getColor(battery ? R.color.green : R.color.text));
        batteryBtn.setVisibility(battery ? View.GONE : View.VISIBLE);

        String url = store.url();
        urlState.setText(url.isEmpty() ? "아직 연결 주소가 없어요." : "저장된 주소: …" + url.substring(Math.max(0, url.length() - 6)));
        int waiting = store.waiting();
        waitState.setText(waiting == 0 ? "보내지 못한 알림 없음" : "보내지 못해 기다리는 알림 " + waiting + "개 (인터넷이 되면 다시 보내요)");
        retryBtn.setVisibility(waiting == 0 ? View.GONE : View.VISIBLE);

        String msg = store.updateMessage();
        updateState.setText(msg.isEmpty() ? updateText : msg + (updateText.isEmpty() ? "" : "\n" + updateText));
        installAllowBtn.setVisibility(updateNeedsPermission && !getPackageManager().canRequestPackageInstalls() ? View.VISIBLE : View.GONE);

        String appsNow = store.apps().toString();
        if (!appsNow.equals(shownApps)) { shownApps = appsNow; drawApps(); }
        List<JSONObject> logs = store.logs();
        String logsNow = logs.toString();
        if (!logsNow.equals(shownLogs)) { shownLogs = logsNow; drawLogs(logs); }
    }

    private void drawApps() {
        appsBox.removeAllViews();
        JSONObject apps = store.apps();
        List<String> pkgs = new ArrayList<>();
        for (Iterator<String> it = apps.keys(); it.hasNext(); ) pkgs.add(it.next());
        pkgs.sort((a, b) -> Long.compare(apps.optJSONObject(b).optLong("last"), apps.optJSONObject(a).optLong("last")));
        if (pkgs.isEmpty()) {
            appsBox.addView(text("아직 없어요.", 13, R.color.muted));
            return;
        }
        for (String pkg : pkgs) {
            JSONObject a = apps.optJSONObject(pkg);
            CheckBox cb = new CheckBox(this);
            cb.setText(a.optString("label", pkg) + "  ·  " + ago(a.optLong("last")));
            cb.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
            cb.setChecked(a.optBoolean("on", true));
            cb.setOnCheckedChangeListener((v, on) -> store.setAppOn(pkg, on));
            appsBox.addView(cb);
        }
    }

    private void drawLogs(List<JSONObject> logs) {
        logBox.removeAllViews();
        if (logs.isEmpty()) {
            logBox.addView(text("아직 보낸 알림이 없어요.", 13, R.color.muted));
            return;
        }
        SimpleDateFormat f = new SimpleDateFormat("M/d HH:mm", Locale.KOREA);
        for (JSONObject l : logs) {
            LinearLayout item = new LinearLayout(this);
            item.setOrientation(LinearLayout.VERTICAL);
            item.setPadding(0, dp(8), 0, dp(8));
            TextView head = text(f.format(new Date(l.optLong("t"))) + "  " + l.optString("app") + "  ·  " + l.optString("status"), 12,
                    l.optBoolean("ok") ? R.color.green : R.color.bad);
            item.addView(head);
            item.addView(text(l.optString("text"), 13, R.color.text));
            logBox.addView(item);
        }
    }

    // ==========================================
    // 동작
    // ==========================================
    private void paste() {
        ClipboardManager cm = getSystemService(ClipboardManager.class);
        ClipData clip = cm == null ? null : cm.getPrimaryClip();
        if (clip != null && clip.getItemCount() > 0 && clip.getItemAt(0).getText() != null) {
            urlInput.setText(clip.getItemAt(0).getText().toString().trim());
            saveUrl();
        } else {
            toast("복사된 글이 없어요");
        }
    }

    private void saveUrl() {
        String u = urlInput.getText().toString().trim();
        if (!u.isEmpty() && (!(u.startsWith("http://") || u.startsWith("https://")) || !u.contains(HOOK_PATH)
                || u.length() <= u.indexOf(HOOK_PATH) + HOOK_PATH.length() + 10)) {
            toast("가계부에서 받은 연결 주소가 아니에요 (…" + HOOK_PATH + "…)");
            return;
        }
        store.setUrl(u);
        toast(u.isEmpty() ? "연결 주소를 지웠어요" : "저장했어요");
        refresh();
    }

    private void sendTest() {
        if (store.url().isEmpty()) {
            toast("연결 주소를 먼저 저장하세요");
            return;
        }
        String now = new SimpleDateFormat("M/d HH:mm", Locale.KOREA).format(new Date());
        Sender.sendTest(this, "[가계부 알림 앱] 시험 승인 1,000원 일시불 " + now + " 앱 연결 시험", () -> ui.post(() -> {
            refresh();
            toast("보냈어요 — 아래 '최근 보낸 알림'과 가계부 확인 대기함을 보세요");
        }));
    }

    private boolean hasAccess() {
        String on = Settings.Secure.getString(getContentResolver(), "enabled_notification_listeners");
        return on != null && on.contains(new ComponentName(this, NotifyListener.class).flattenToString());
    }

    // ==========================================
    // 작은 도우미
    // ==========================================
    private LinearLayout card(LinearLayout root, String head) {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(14), dp(12), dp(14), dp(14));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(getColor(R.color.card));
        bg.setCornerRadius(dp(12));
        bg.setStroke(dp(1), 0xFFE3E5E1);
        c.setBackground(bg);
        TextView h = text(head, 15, R.color.green);
        h.setTypeface(Typeface.DEFAULT_BOLD);
        c.addView(h);
        LinearLayout.LayoutParams lp = gap(14);
        root.addView(c, lp);
        return c;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(getColor(color));
        t.setLineSpacing(0, 1.15f);
        return t;
    }

    private Button button(String s, View.OnClickListener on) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setOnClickListener(on);
        return b;
    }

    private LinearLayout.LayoutParams gap(int topDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(topDp);
        return lp;
    }

    private LinearLayout.LayoutParams weight() {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        lp.gravity = Gravity.CENTER_VERTICAL;
        return lp;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    private static String ago(long t) {
        long m = (System.currentTimeMillis() - t) / 60000;
        if (m < 1) return "방금";
        if (m < 60) return m + "분 전";
        if (m < 60 * 24) return (m / 60) + "시간 전";
        return (m / 60 / 24) + "일 전";
    }
}
