package kr.home.ledgernotify;

import android.app.Activity;
import android.app.AlertDialog;
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
public class SettingsActivity extends Activity implements Updater.Host {
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
    private Switch enabledSwitch, alertSwitch, alertPendingSwitch, dutyPushSwitch, ledgerPushSwitch;
    private TextView alertState;
    private LinearLayout appsBox, logBox, ignoreBox;
    private EditText ignoreInput;
    private String shownLogs = "", shownApps = "", shownIgnores = "";

    /** 어느 설정을 보일지: 앱(홈 탭의 '설정': 주소·버전·로그아웃), 휴대폰 결제 알림(가계부 설정에서), 모두(처음 쓸 때) */
    static final String EXTRA_SECTION = "section";
    /** 이 글로 곧바로 '이런 알림 안 받기' 낱말 고르기 창을 띄움 (가계부의 버린 알림에서) */
    static final String EXTRA_IGNORE_TEXT = "ignore_text";
    static final String SECTION_APP = "app", SECTION_PHONE = "phone", SECTION_ALL = "all";
    /** 홈 > 설정의 결제 알림 줄 하나씩 (1.13부터): 그 칸만 보임 */
    static final String SECTION_ACCESS = "access", SECTION_LINK = "link", SECTION_IGNORE = "ignore",
            SECTION_APPS = "apps", SECTION_LOGS = "logs";
    static final List<String> ONE_SECTIONS = java.util.Arrays.asList(SECTION_ACCESS, SECTION_LINK, SECTION_IGNORE, SECTION_APPS, SECTION_LOGS);
    private String section = SECTION_ALL;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        store = new Store(this);
        String sec = getIntent().getStringExtra(EXTRA_SECTION);
        if (SECTION_APP.equals(sec) || SECTION_PHONE.equals(sec) || ONE_SECTIONS.contains(sec)) section = sec;
        setContentView(build());
        String ignoreText = getIntent().getStringExtra(EXTRA_IGNORE_TEXT);
        if (b == null && ignoreText != null && !ignoreText.trim().isEmpty()) ui.post(() -> pickIgnore(ignoreText));
    }

    @Override
    protected void onResume() {
        super.onResume();
        Updater.resumed(this);   // 기다리던 업데이트 확인 창 (autoDue보다 먼저)
        if (hasAccess(this)) NotificationListenerService.requestRebind(new ComponentName(this, NotifyListener.class));
        urlInput.setText(store.url());
        enabledSwitch.setChecked(store.enabled());
        alertSwitch.setChecked(store.alertOn());
        dutyPushSwitch.setChecked(store.dutyPushOn());
        ledgerPushSwitch.setChecked(store.ledgerPushOn());
        alertPendingSwitch.setChecked(store.alertPendingOn());
        alertPendingSwitch.setEnabled(store.alertOn());
        showAlertState();
        shownLogs = shownApps = shownIgnores = "";
        ui.post(tick);
        // '이 앱의 설치 허용'을 켜러 갔다 돌아온 때는 바로 이어서 설치
        if (Updater.autoDue(updateNeedsPermission)) checkUpdate(true);
    }

    /** 로그아웃: 서버에 알리고 이 앱의 로그인 쿠키를 지움 → 돌아가면 페이지를 모두 다시 읽음 */
    private void logout() {
        String origin = Store.origin(store.site());
        String cookie = DutyWidgets.cookie(this);
        new Thread(() -> {
            if (cookie != null && !origin.isEmpty()) {
                try {
                    java.net.HttpURLConnection con = (java.net.HttpURLConnection) new java.net.URL(origin + "/api/ledger/session").openConnection();
                    con.setRequestMethod("POST");
                    con.setDoOutput(true);
                    con.setConnectTimeout(5000);
                    con.setReadTimeout(5000);
                    con.setRequestProperty("Content-Type", "application/json");
                    con.setRequestProperty("Cookie", cookie);
                    con.getOutputStream().write("{\"action\":\"logout\"}".getBytes("UTF-8"));
                    con.getResponseCode();
                    con.disconnect();
                } catch (Exception ignored) { /* 서버에 못 알려도 이 휴대폰에서는 지움 */ }
            }
            ui.post(() -> android.webkit.CookieManager.getInstance().removeAllCookies(done -> {
                android.webkit.CookieManager.getInstance().flush();
                MainActivity.reloadPages = true;
                toast("로그아웃했어요");
                finish();
            }));
        }).start();
    }

    @Override
    public void checkUpdate(boolean auto) {
        Updater.check(this, auto, (text, needPermission) -> ui.post(() -> {
            updateText = text;
            updateNeedsPermission = needPermission;
            refresh();
        }));
    }

    @Override
    protected void onPause() {
        super.onPause();
        Updater.paused(this);
        ui.removeCallbacks(tick);
    }

    // ==========================================
    // 화면 만들기
    // ==========================================
    private View build() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(16), dp(16), dp(24));

        boolean one = ONE_SECTIONS.contains(section);
        boolean app = SECTION_APP.equals(section) || SECTION_ALL.equals(section), phone = !SECTION_APP.equals(section) && !one;
        TextView title = text(titleFor(section), 22, R.color.text);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        root.addView(title);
        root.addView(text(introFor(section), 13, R.color.muted), gap(4));

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
        perm.addView(text("목록에서 'YeYe홈'이 회색이라 켤 수 없으면: 아래 '앱 정보 열기' → 오른쪽 위 ⋮ → '제한된 설정 허용' 뒤 다시 켜세요.", 12, R.color.muted), gap(8));
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
        link.addView(text("가계부 탭 → 위쪽 '설정' → 결제 알림 연결 → '이 휴대폰 앱에 연결'을 누르면 저절로 들어가요. 직접 넣으려면 받은 연결 주소를 붙여 넣으세요.", 12, R.color.muted));
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

        // ---- 금액 인식 알림
        LinearLayout alert = card(root, "금액 인식 알림");
        alertSwitch = new Switch(this);
        alertSwitch.setText("금액 인식 알림");
        alertSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        alertSwitch.setOnCheckedChangeListener((sw, on) -> {
            store.setAlertOn(on);
            alertPendingSwitch.setEnabled(on);
            if (on) askNotifyPermission();
            showAlertState();
        });
        alert.addView(alertSwitch);
        alert.addView(text("결제를 확인 대기함에 넣으면 금액과 가게를 휴대폰 알림으로 알려 줘요. 누르면 확인 대기함이 열려요.", 12, R.color.muted), gap(2));
        alertPendingSwitch = new Switch(this);
        alertPendingSwitch.setText("못 보낸 것도 알림");
        alertPendingSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        alertPendingSwitch.setOnCheckedChangeListener((sw, on) -> store.setAlertPendingOn(on));
        alert.addView(alertPendingSwitch, gap(12));
        alert.addView(text("인터넷이 안 될 때 금액만 알아본 결제도 알려 줘요. 나중에 보내지면 그 알림이 '넣음'으로 바뀌어요.", 12, R.color.muted), gap(2));
        alertState = text("", 13, R.color.text);
        alertState.setOnClickListener(v -> {
            if (store.alertOn() && !Notifier.allowed(this)) askNotifyPermission();
        });
        alert.addView(alertState, gap(10));

        // ---- 근무표·가계부 변경 알림 (FCM, DutyPush)
        LinearLayout dutyCard = card(root, "근무표·가계부 변경 알림");
        dutyPushSwitch = new Switch(this);
        dutyPushSwitch.setText("근무표 변경 알림");
        dutyPushSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        dutyPushSwitch.setOnCheckedChangeListener((sw, on) -> {
            if (on == store.dutyPushOn()) return;
            store.setDutyPushOn(on);
            DutyPush.changed(this);
            if (on) askNotifyPermission();
        });
        dutyCard.addView(dutyPushSwitch);
        dutyCard.addView(text(DutyPush.available(this)
                ? "다른 사람이 근무표를 고치면 바로 알려 줘요 (내가 고친 것은 안 알려요). 누르면 근무표가 열려요."
                : "이 앱 파일에는 알림 받기 설정(Firebase)이 들어 있지 않아 알림을 받을 수 없어요.", 12, R.color.muted), gap(2));
        ledgerPushSwitch = new Switch(this);
        ledgerPushSwitch.setText("가계부 변경 알림");
        ledgerPushSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        ledgerPushSwitch.setOnCheckedChangeListener((sw, on) -> {
            if (on == store.ledgerPushOn()) return;
            store.setLedgerPushOn(on);
            DutyPush.changed(this);
            if (on) askNotifyPermission();
        });
        dutyCard.addView(ledgerPushSwitch, gap(12));
        if (DutyPush.available(this)) {
            dutyCard.addView(text("다른 사람이 가계부에 기록을 넣거나 고치거나 지우면 알려 줘요 (결제 알림 확정 포함). 누르면 가계부가 열려요.",
                    12, R.color.muted), gap(2));
        }

        // ---- 무시할 알림 (이 휴대폰에만)
        LinearLayout ign = card(root, "무시할 알림");
        ign.addView(text("알림 글에 이 표현이 있으면 가계부로 보내지 않아요 (이 휴대폰에만, 띄어쓰기는 무시). '최근 알림'의 '이런 알림 안 받기'로도 넣을 수 있어요.", 12, R.color.muted));
        ignoreBox = new LinearLayout(this);
        ignoreBox.setOrientation(LinearLayout.VERTICAL);
        ign.addView(ignoreBox, gap(6));
        LinearLayout irow = new LinearLayout(this);
        irow.setGravity(Gravity.CENTER_VERTICAL);
        ignoreInput = new EditText(this);
        ignoreInput.setHint("표현 넣기 (예: 결제예정)");
        ignoreInput.setSingleLine(true);
        ignoreInput.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        irow.addView(ignoreInput, weight());
        irow.addView(button("추가", v -> {
            if (addIgnore(ignoreInput.getText().toString())) ignoreInput.setText("");
        }));
        ign.addView(irow, gap(4));

        // ---- 3. 앱
        LinearLayout apps = card(root, "3. 결제 알림을 보낸 앱");
        apps.addView(text("결제 알림처럼 보이는 글을 보낸 앱이 여기 쌓여요. 체크를 끄면 그 앱 알림은 보내지 않아요.", 12, R.color.muted));
        appsBox = new LinearLayout(this);
        appsBox.setOrientation(LinearLayout.VERTICAL);
        apps.addView(appsBox, gap(6));

        // ---- 4. 기록
        LinearLayout logs = card(root, "최근 알림");
        logBox = new LinearLayout(this);
        logBox.setOrientation(LinearLayout.VERTICAL);
        logs.addView(logBox);

        // ---- 로그아웃 (앱 설정): 이 휴대폰에서 가계부·근무표·홈 모두
        LinearLayout out = card(root, "로그인");
        out.addView(text("이 휴대폰 앱에서 로그아웃해요. 결제 알림 연결은 그대로예요.", 12, R.color.muted));
        out.addView(button("로그아웃", v -> logout()), gap(6));

        // 들어온 곳에 따라 보일 칸만 (상태 갱신은 모든 칸에 그대로)
        ver.setVisibility(app ? View.VISIBLE : View.GONE);
        out.setVisibility(SECTION_APP.equals(section) ? View.VISIBLE : View.GONE);
        dutyCard.setVisibility(one ? View.GONE : View.VISIBLE);
        for (View v : new View[]{perm, link, alert, ign, apps, logs}) v.setVisibility(phone ? View.VISIBLE : View.GONE);
        // 결제 알림 줄 하나로 들어왔으면 그 칸만 (칸 제목은 화면 제목과 같아 숨김)
        if (one) {
            LinearLayout only = SECTION_ACCESS.equals(section) ? perm : SECTION_LINK.equals(section) ? link
                    : SECTION_IGNORE.equals(section) ? ign : SECTION_APPS.equals(section) ? apps : logs;
            only.setVisibility(View.VISIBLE);
            only.getChildAt(0).setVisibility(View.GONE);
        }

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        return sv;
    }

    // ==========================================
    // 상태 보이기 (2초마다)
    // ==========================================
    private void refresh() {
        boolean access = hasAccess(this);
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
        List<String> ignores = store.ignores();
        if (!ignores.toString().equals(shownIgnores)) { shownIgnores = ignores.toString(); drawIgnores(ignores); }
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
            // 보낸 결제 알림이면 '이런 알림 안 받기' (그 알림 글의 낱말로 무시할 표현 넣기).
            // 1.4 이하에서 쌓인 기록은 글 전체(full)가 없어 미리보기 글로
            String full0 = l.optString("full", "");
            final String full = full0.isEmpty() ? l.optString("text", "") : full0;
            if (!l.optBoolean("filtered") && !"시험".equals(l.optString("app")) && !full.isEmpty()) {
                Button no = button("이런 알림 안 받기", v -> pickIgnore(full));
                no.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                lp.topMargin = dp(4);
                item.addView(no, lp);
            }
            logBox.addView(item);
        }
    }

    private void drawIgnores(List<String> ignores) {
        ignoreBox.removeAllViews();
        if (ignores.isEmpty()) {
            ignoreBox.addView(text("아직 없어요.", 13, R.color.muted));
            return;
        }
        for (String w : ignores) {
            LinearLayout row = new LinearLayout(this);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.addView(text(w, 14, R.color.bad), weight());
            Button del = button("빼기", v -> { store.removeIgnore(w); refresh(); });
            del.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            row.addView(del);
            ignoreBox.addView(row);
        }
    }

    /** 무시할 표현 넣기. 넣었으면 true (아니면 그 이유를 알려 줌) */
    private boolean addIgnore(String word) {
        String err = store.addIgnore(word);
        if (err != null) { toast(err); return false; }
        toast("'" + word.trim() + "'이(가) 들어간 알림은 이제 보내지 않아요");
        refresh();
        return true;
    }

    /** '이런 알림 안 받기' (1.27부터): 위에 알림 원문(끌어서 고르면 아래 칸에), 가운데 낱말 칩(두 개를 차례로 누르면
     *  원문에서 그 사이를 통째로, 예: hi → pass = "hi-pass"), 아래 입력칸에서 고쳐 '거르기에 추가' */
    private void pickIgnore(String full) {
        // 낱말: 두 글자 이상, 숫자로 시작하는 것(금액·시각) 빼고, 원문에서의 자리와 함께
        List<int[]> spans = new ArrayList<>();
        List<String> seen = new ArrayList<>();
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("[가-힣A-Za-z0-9]+").matcher(full);
        while (m.find() && spans.size() < 20) {
            String w = m.group();
            if (w.length() < 2 || w.matches("[0-9].*") || seen.contains(w)) continue;
            seen.add(w);
            spans.add(new int[]{m.start(), m.end()});
        }

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(8), dp(20), 0);
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setHint("거를 표현");

        box.addView(text("원문 (끌어서 고르면 아래 칸에 들어가요)", 12, R.color.muted));
        // 원문: 고칠 수 없고 고르기만 (고른 부분이 바뀔 때마다 입력칸으로)
        EditText raw = new EditText(this) {
            @Override protected void onSelectionChanged(int a, int b) {
                super.onSelectionChanged(a, b);
                if (input != null && b > a && getText() != null) input.setText(getText().subSequence(Math.min(a, b), Math.max(a, b)).toString().trim());
            }
        };
        raw.setText(full);
        raw.setKeyListener(null);
        raw.setTextIsSelectable(true);
        raw.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        raw.setTextColor(getColor(R.color.text));
        raw.setPadding(dp(10), dp(8), dp(10), dp(8));
        GradientDrawable rawBg = new GradientDrawable();
        rawBg.setColor(getColor(R.color.bg));
        rawBg.setCornerRadius(dp(8));
        raw.setBackground(rawBg);
        LinearLayout.LayoutParams rawLp = gap(4);
        box.addView(raw, rawLp);

        if (!spans.isEmpty()) {
            box.addView(text("낱말 (두 개를 누르면 그 사이를 통째로)", 12, R.color.muted), gap(12));
            WrapLayout chips = new WrapLayout(this, dp(6));
            List<TextView> chipViews = new ArrayList<>();
            int[] pick = {-1, -1};   // 처음 누른 칩, 둘째로 누른 칩
            Runnable paint = () -> {
                int lo = pick[1] < 0 ? pick[0] : Math.min(pick[0], pick[1]), hi = pick[1] < 0 ? pick[0] : Math.max(pick[0], pick[1]);
                for (int i = 0; i < chipViews.size(); i++) {
                    boolean end = i == pick[0] || i == pick[1], mid = !end && lo >= 0 && i > lo && i < hi;
                    GradientDrawable bg = new GradientDrawable();
                    bg.setCornerRadius(dp(14));
                    bg.setColor(getColor(end ? R.color.brand_soft : mid ? R.color.bg : R.color.card));
                    bg.setStroke(dp(1), end ? getColor(R.color.ink) : 0xFFD1D5DB);
                    chipViews.get(i).setBackground(bg);
                    chipViews.get(i).setTextColor(getColor(end ? R.color.ink : R.color.text));
                }
            };
            for (int i = 0; i < spans.size(); i++) {
                final int idx = i;
                int[] sp = spans.get(i);
                TextView c = text(full.substring(sp[0], sp[1]), 13, R.color.text);
                c.setPadding(dp(10), dp(5), dp(10), dp(5));
                c.setOnClickListener(v -> {
                    if (pick[0] < 0 || pick[1] >= 0) { pick[0] = idx; pick[1] = -1; }
                    else pick[1] = idx;
                    int a = pick[0], b2 = pick[1] < 0 ? pick[0] : pick[1];
                    int from = Math.min(spans.get(a)[0], spans.get(b2)[0]), to = Math.max(spans.get(a)[1], spans.get(b2)[1]);
                    input.setText(full.substring(from, to).trim());
                    input.setSelection(input.getText().length());
                    paint.run();
                });
                chipViews.add(c);
                chips.addView(c);
            }
            paint.run();
            box.addView(chips, gap(4));
        }
        box.addView(input, gap(12));

        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        AlertDialog dlg = new AlertDialog.Builder(this)
                .setTitle("어떤 표현이 있으면 거를까요?")
                .setView(scroll)
                .setPositiveButton("거르기에 추가", null)
                .setNegativeButton("취소", null)
                .create();
        // 넣지 못하면(빈 칸·이미 있음 등) 창을 닫지 않음
        dlg.setOnShowListener(x -> dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            if (addIgnore(input.getText().toString())) dlg.dismiss();
        }));
        dlg.show();
    }

    /** 칩을 줄이 넘치면 다음 줄로 늘어놓는 칸 */
    static class WrapLayout extends ViewGroup {
        private final int gapPx;
        WrapLayout(android.content.Context c, int gapPx) { super(c); this.gapPx = gapPx; }

        @Override protected void onMeasure(int wSpec, int hSpec) {
            int width = MeasureSpec.getSize(wSpec), x = 0, y = 0, rowH = 0;
            for (int i = 0; i < getChildCount(); i++) {
                View ch = getChildAt(i);
                ch.measure(MeasureSpec.makeMeasureSpec(width, MeasureSpec.AT_MOST), MeasureSpec.UNSPECIFIED);
                if (x > 0 && x + ch.getMeasuredWidth() > width) { x = 0; y += rowH + gapPx; rowH = 0; }
                x += ch.getMeasuredWidth() + gapPx;
                rowH = Math.max(rowH, ch.getMeasuredHeight());
            }
            setMeasuredDimension(width, y + rowH);
        }

        @Override protected void onLayout(boolean changed, int l, int t, int r, int b) {
            int width = r - l, x = 0, y = 0, rowH = 0;
            for (int i = 0; i < getChildCount(); i++) {
                View ch = getChildAt(i);
                int w = ch.getMeasuredWidth(), h = ch.getMeasuredHeight();
                if (x > 0 && x + w > width) { x = 0; y += rowH + gapPx; rowH = 0; }
                ch.layout(x, y, x + w, y + h);
                x += w + gapPx;
                rowH = Math.max(rowH, h);
            }
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
        Sender.sendTest(this, "[YeYe홈 앱] 시험 승인 1,000원 일시불 " + now + " 앱 연결 시험", () -> ui.post(() -> {
            refresh();
            toast("보냈어요 — 가계부 확인 대기함과 '최근 알림'을 보세요");
        }));
    }

    /** 알림 권한: 처음이면 권한 창, 이미 거절했으면 이 앱의 알림 설정 화면 */
    private void askNotifyPermission() {
        if (Notifier.allowed(this)) return;
        if (android.os.Build.VERSION.SDK_INT >= 33 && (!store.askedNotifyPermission()
                || shouldShowRequestPermissionRationale(android.Manifest.permission.POST_NOTIFICATIONS))) {
            store.setAskedNotifyPermission();
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 2);
        } else {
            startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        showAlertState();
    }

    private void showAlertState() {
        if (alertState == null) return;
        if (!store.alertOn()) alertState.setText("꺼짐");
        else if (Notifier.allowed(this)) alertState.setText("✓ 알림을 띄울 수 있어요");
        else alertState.setText("✗ 알림 권한이 꺼져 있어요 — 눌러서 켜기");
    }

    static boolean hasAccess(android.content.Context c) {
        String on = Settings.Secure.getString(c.getContentResolver(), "enabled_notification_listeners");
        return on != null && on.contains(new ComponentName(c, NotifyListener.class).flattenToString());
    }

    private static String titleFor(String sec) {
        switch (sec) {
            case SECTION_APP: return "앱 설정";
            case SECTION_PHONE: return "휴대폰 결제 알림 설정";
            case SECTION_ACCESS: return "알림 읽기 권한";
            case SECTION_LINK: return "결제 알림 연결";
            case SECTION_IGNORE: return "무시할 알림";
            case SECTION_APPS: return "결제 알림을 보낸 앱";
            case SECTION_LOGS: return "최근 알림";
            default: return "YeYe홈 설정";
        }
    }

    private static String introFor(String sec) {
        switch (sec) {
            case SECTION_APP: return "앱 전체에 쓰는 설정이에요. 가계부·근무표 설정은 그 탭에서 위쪽 '설정'을 누르세요.";
            case SECTION_ACCESS: return "휴대폰에 뜨는 결제 알림을 읽으려면 이 권한이 있어야 해요. 배터리 절약을 끄면 앱이 멈추지 않아요.";
            case SECTION_LINK: return "이 휴대폰의 결제 알림을 보낼 가계부 주소예요.";
            case SECTION_IGNORE: return "가계부로 보내지 않을 알림을 표현으로 골라요.";
            case SECTION_APPS: return "결제 알림을 보낸 앱마다 보낼지 고를 수 있어요.";
            case SECTION_LOGS: return "이 휴대폰이 읽은 결제 알림과 보낸 결과예요.";
            default: return "카드 결제 알림을 가계부의 확인 대기함으로 보내요. 결제 알림처럼 보이는 글만 보내고, 다른 알림은 휴대폰 밖으로 나가지 않아요.";
        }
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
        TextView h = text(head, 15, R.color.ink);
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
