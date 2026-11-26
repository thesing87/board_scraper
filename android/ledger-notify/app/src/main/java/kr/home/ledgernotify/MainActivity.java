package kr.home.ledgernotify;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 첫 화면 (YeYe홈): 아래쪽 탭으로 홈(/yeye/, 근무표·가계부 요약)·가계부(/ledger/)·근무표(/duty/) 웹 페이지를 오감.
 * 탭마다 웹 화면을 따로 둬서 오가도 보던 곳이 그대로. 앱을 열면 홈부터 (알림을 누르면 가계부, 근무표 위젯을 누르면 근무표).
 * 위쪽 줄의 '설정'은 보고 있는 탭의 설정: 홈 → 전체 설정(앱 파일·버전·로그아웃), 가계부·근무표 → 그 페이지의 설정 화면.
 * 주소는 고정 (strings.xml의 site_url).
 * 페이지는 window.LedgerApp(Bridge)로 이 앱을 알아보고, 가계부의 '이 휴대폰 앱에 연결'을 누르면 연결 주소를 넘겨줌.
 * 다른 주소의 링크는 브라우저로 엶 (앱 안에는 홈·가계부·근무표만)
 * 1.30부터: 좌우로 빠르게 밀면 옆 탭으로 (홈 · 가계부 · 근무표 순서), 페이지 맨 위에서 아래로 끌어 놓으면 그 탭을 새로 읽음.
 * 손가락을 댈 때 페이지의 window.appGesture(x, y)에 물어 봄 (창이 열렸거나 자기 밀기가 있는 곳이면 하지 않음)
 */
public class MainActivity extends Activity implements Updater.Host {
    private static final int PICK_FILE = 1, PICK_PHOTO = 2;
    static final int TAB_LEDGER = 0, TAB_DUTY = 1, TAB_HOME = 2;
    private static final String[] PATHS = {"/ledger/", "/duty/", "/yeye/"};
    /** 이 탭으로 열기 (근무표 위젯을 누름) */
    static final String EXTRA_TAB = "tab";
    /** 근무표에서 이 날짜(yyyy-MM-dd)를 열기, 그 사람 근무표로 (한 달 위젯에서 날짜를 누름, 1.25부터) */
    static final String EXTRA_DAY = "day", EXTRA_PERSON = "person";
    /** 앱 설정에서 로그아웃함: 돌아오면 세 페이지를 모두 다시 읽음 */
    static volatile boolean reloadPages;

    private Store store;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;                     // 지금 보이는 탭의 웹 화면
    private final WebView[] webs = new WebView[3];
    private final String[] loaded = {"", "", ""};   // 탭마다 띄운 주소 (가계부 외에는 그 탭을 처음 볼 때 엶)
    // 앱이 탭에 새 페이지를 엶(홈 카드 → 가계부 그 기록 등): 다 읽으면 그 탭의 이전 기록을 지워, 뒤로가기가
    // 예전 가계부 페이지 전체로 돌아가지 않고 페이지 안의 열린 것을 닫은 뒤 홈 탭으로 감
    private final boolean[] freshLoad = new boolean[3];
    private int tab = -1;
    private final TextView[] tabLabels = new TextView[3];
    private final ImageView[] tabIcons = new ImageView[3];
    private final View[] tabLines = new View[3];
    private TextView banner;
    private FrameLayout pages;
    /** 끌어내려 새로고침 표시 (흰 동그라미 + 새로고침 아이콘) */
    private FrameLayout pullDot;
    private ImageView pullIcon;
    private android.animation.ObjectAnimator pullSpin;
    private static final int[] ORDER = {TAB_HOME, TAB_LEDGER, TAB_DUTY};   // 위쪽 탭 순서 (좌우로 밀 때)
    private static final int PULL_GO = 72;   // 표시가 이만큼(dp) 내려온 뒤 놓으면 새로고침
    private float downX, downY;
    private long downAt;
    private volatile String gestureOk;       // 페이지의 답: 'h' 탭 넘기기 가능, 'v' 새로고침 가능 (아직 답이 없으면 null)
    private boolean tracking, pulling, refreshing;
    private ProgressBar progress;
    private String loadedSite = "";
    private volatile String pageOrigin = "";
    private ValueCallback<Uri[]> fileCallback;
    private WebView fileView;   // 파일 고르기를 연 페이지 (사진을 넘긴 뒤 다시 그리게)
    private boolean askedSite;
    private boolean loadFailed;
    private volatile String updateText = "";
    private boolean updateNeedsPermission;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        store = new Store(this);
        setContentView(build());
        openInbox = getIntent().getBooleanExtra(Notifier.EXTRA_INBOX, false);
        takeDutyDay(getIntent());
        // 홈부터 (금액 인식 알림·가계부 변경 알림을 눌러 열면 가계부, 근무표 위젯·근무표 변경 알림을 눌러 열면 근무표)
        selectTab(openInbox || isLedgerPush(getIntent()) ? TAB_LEDGER : isDutyPush(getIntent()) ? TAB_DUTY : getIntent().getIntExtra(EXTRA_TAB, TAB_HOME));
        DutyPush.ensureChannel(this);
        // 금액 인식 알림을 띄우려면 (안드로이드 13 이상) 알림 권한: 알림 읽기 권한을 켠 뒤 처음 한 번만 물음
        if (android.os.Build.VERSION.SDK_INT >= 33 && store.alertOn() && !Notifier.allowed(this)
                && !store.askedNotifyPermission() && SettingsActivity.hasAccess(this)) {
            store.setAskedNotifyPermission();
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 2);
        } else if (android.os.Build.VERSION.SDK_INT >= 33 && store.anyPushOn() && !Notifier.allowed(this)
                && !store.askedDutyNotify() && !store.site().isEmpty()) {
            // 근무표·가계부 변경 알림: 처음 한 번만 물음
            store.setAskedDutyNotify();
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 3);
        }
    }

    /** 앱이 뒤에 있을 때 시스템이 띄운 근무표 변경 알림을 누름 (FCM 데이터가 extras로 옴) */
    private static boolean isDutyPush(Intent i) {
        return DutyPush.KIND_DUTY.equals(i.getStringExtra(DutyPush.EXTRA_KIND));
    }

    /** 가계부 변경 알림을 누름 (1.14부터) */
    private static boolean isLedgerPush(Intent i) {
        return DutyPush.KIND_LEDGER.equals(i.getStringExtra(DutyPush.EXTRA_KIND));
    }

    /** 금액 인식 알림을 누름: 가계부를 새로 읽고 확인 대기함으로 */
    private boolean openInbox;

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent.getBooleanExtra(Notifier.EXTRA_INBOX, false) && !loadedSite.isEmpty()) {
            openInbox = true;
            selectTab(TAB_LEDGER);
            webs[TAB_LEDGER].reload();
        } else if (isDutyPush(intent)) {
            selectTab(TAB_DUTY);
            webs[TAB_DUTY].reload();
        } else if (isLedgerPush(intent) && !loadedSite.isEmpty()) {
            selectTab(TAB_LEDGER);
            webs[TAB_LEDGER].reload();
        } else if (intent.hasExtra(EXTRA_TAB)) {
            selectTab(intent.getIntExtra(EXTRA_TAB, TAB_HOME));
            if (takeDutyDay(intent) && dutyLoaded) openDutyDay();
        }
    }

    /** 위젯에서 누른 날짜 (근무표 페이지가 다 읽히면 그 날짜로) */
    private String dutyDay;
    private int dutyPerson;
    private boolean dutyLoaded;

    private boolean takeDutyDay(Intent i) {
        String day = i.getStringExtra(EXTRA_DAY);
        if (day == null || !day.matches("\\d{4}-\\d{2}-\\d{2}")) return false;
        dutyDay = day;
        dutyPerson = i.getIntExtra(EXTRA_PERSON, 0);
        i.removeExtra(EXTRA_DAY);   // 화면을 돌려 다시 만들어도 또 가지 않게
        return true;
    }

    /** 근무표 페이지에 그 날짜를 열라고 함 (페이지가 아직 준비 중이면 잠깐씩 기다렸다가) */
    private void openDutyDay() {
        if (dutyDay == null) return;
        String js = "(function t(n){if(window.appOpenDay){window.appOpenDay('" + dutyDay + "'," + dutyPerson + ");}"
                + "else if(n>0){setTimeout(function(){t(n-1);},300);}})(30)";
        dutyDay = null;
        webs[TAB_DUTY].evaluateJavascript(js, null);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        showBanner();
        if (code == ASK_CALENDAR) {
            boolean ok = results.length > 0 && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED;
            // '다시 묻지 않음'이라 창이 안 뜸: 앱 정보 화면에서 켜게 함
            if (!ok && System.currentTimeMillis() - askedCalendarAt < 500
                    && !shouldShowRequestPermissionRationale(android.Manifest.permission.READ_CALENDAR)) {
                toast("권한 → 캘린더에서 허용해 주세요");
                startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName())));
            }
            calendarChanged();
        }
    }

    private static final int ASK_CALENDAR = 4;
    private long askedCalendarAt;

    /** 캘린더 읽기 권한 묻기 (바로 답이 오면 '다시 묻지 않음'이라 창이 안 뜬 것) */
    private void askCalendar() {
        askedCalendarAt = System.currentTimeMillis();
        requestPermissions(new String[]{android.Manifest.permission.READ_CALENDAR}, ASK_CALENDAR);
    }

    /** 근무표 페이지에 캘린더 설정·권한이 바뀌었다고 알림 (일정을 새로 읽음) */
    private void calendarChanged() {
        webs[TAB_DUTY].evaluateJavascript("window.appCalendarChanged && window.appCalendarChanged()", null);
    }

    /** 확인 대기함이 그려질 때까지 잠깐 기다렸다가 그리로 (대기함이 비었으면 그냥 첫 화면) */
    private void scrollToInbox() {
        if (!openInbox) return;
        openInbox = false;
        webs[TAB_LEDGER].evaluateJavascript("(function t(n){var e=document.getElementById('inbox-sec');"
                + "if(e&&!e.hidden){e.scrollIntoView({block:'start'});}else if(n>0){setTimeout(function(){t(n-1);},300);}})(20)", null);
    }

    @Override
    protected void onResume() {
        super.onResume();
        Updater.resumed(this);   // 기다리던 업데이트 확인 창 (autoDue보다 먼저)
        for (WebView w : webs) w.onResume();
        // 앱 정보 화면에서 캘린더 권한을 켜고 돌아왔을 수 있음
        if (!loaded[TAB_DUTY].isEmpty() && store.calendarOn()) calendarChanged();
        String site = store.site();
        if (site.isEmpty()) {
            // 처음: 가계부 주소부터 (설정 화면에서 넣으면 돌아와서 엶)
            if (!askedSite) {
                askedSite = true;
                openSettings(SettingsActivity.SECTION_ALL);
            }
        } else if (!site.equals(loadedSite) || reloadPages) {
            reloadPages = false;
            loadedSite = site;
            pageOrigin = Store.origin(site);
            for (int k = 0; k < 3; k++) loaded[k] = "";
            load(TAB_LEDGER, null);
            if (tab != TAB_LEDGER) load(tab, null);
        }
        if (Updater.autoDue(updateNeedsPermission)) checkUpdate(true);
        DutyPush.sync(this);
        showBanner();
    }

    @Override
    protected void onPause() {
        super.onPause();
        Updater.paused(this);
        for (WebView w : webs) w.onPause();
        CookieManager.getInstance().flush();   // 가계부 로그인 쿠키를 바로 저장
        // 앱에서 로그인했거나 근무표를 봤으면 위젯도 새로 (위젯이 있을 때만)
        if (DutyWidgets.any(this)) DutyWidgets.refreshAll(this);
    }

    /**
     * 뒤로가기: 페이지에 열린 것(설정·고치기·색 고르기·메모 목록 등)이 있으면 그것부터 닫고,
     * 가계부·근무표 탭이면 홈 탭으로 (앱이 탭에 새 페이지를 열면 그 탭의 이전 기록은 지우므로 예전 페이지로 돌아가지 않음), 홈 탭이면 '한 번 더 누르면 종료' 안내
     * → 2초 안에 한 번 더 누르면 앱을 뒤로 보냄 (다시 열면 보던 화면 그대로)
     */
    private long backAt;

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("(window.ledgerBack && window.ledgerBack()) ? 'closed' : ''", r -> {
            if (r != null && r.contains("closed")) return;
            if (web.canGoBack()) {
                web.goBack();
                return;
            }
            if (tab != TAB_HOME) {
                selectTab(TAB_HOME);
                return;
            }
            long now = System.currentTimeMillis();
            if (now - backAt < 2000) {
                backAt = 0;
                moveTaskToBack(true);
            } else {
                backAt = now;
                Toast.makeText(this, "뒤로 버튼을 한 번 더 누르면 종료돼요", Toast.LENGTH_SHORT).show();
            }
        });
    }

    @Override
    public void checkUpdate(boolean auto) {
        Updater.check(this, auto, (text, needPermission) -> ui.post(() -> {
            updateText = text;
            updateNeedsPermission = needPermission;
            showBanner();
        }));
    }

    private void openSettings(String section) {
        startActivity(new Intent(this, SettingsActivity.class).putExtra(SettingsActivity.EXTRA_SECTION, section));
    }

    // ==========================================
    // 화면
    // ==========================================
    private View build() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(getColor(R.color.bg));

        // ---- 위쪽 한 줄: 탭(홈 | 가계부 | 근무표, 아이콘 위·이름 아래, 고른 탭은 검정 + 검정 밑줄, 나머지는 회색)
        // 흰 바탕, 아래에 옅은 선. 제목·새로고침 버튼은 없음 (새로고침은 페이지 맨 위에서 끌어내리기)
        // (설정은 각 페이지의 아래 메뉴에, 이 휴대폰의 것도 홈 > 설정. 페이지를 못 열면 위 안내 줄을 눌러 앱 설정)
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(getColor(R.color.bar));
        bar.setPadding(dp(8), 0, dp(8), 0);
        bar.addView(tabButton(TAB_HOME, "홈", R.drawable.ic_tab_home), new LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.MATCH_PARENT));
        bar.addView(tabButton(TAB_LEDGER, "가계부", R.drawable.ic_tab_ledger), new LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.MATCH_PARENT));
        bar.addView(tabButton(TAB_DUTY, "근무표", R.drawable.ic_tab_duty), new LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56)));
        View barLine = new View(this);
        barLine.setBackgroundColor(getColor(R.color.bar_line));
        root.addView(barLine, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)));

        // ---- 할 일 한 줄 (누르면 그 화면으로)
        banner = new TextView(this);
        banner.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        banner.setTextColor(0xFF633806);
        banner.setBackgroundColor(0xFFFAEEDA);
        banner.setPadding(dp(16), dp(10), dp(16), dp(10));
        banner.setVisibility(View.GONE);
        root.addView(banner, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setVisibility(View.GONE);
        root.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        // ---- 탭마다 웹 화면 하나 (로그인 쿠키는 함께 씀)
        CookieManager.getInstance().setAcceptCookie(true);
        pages = new FrameLayout(this);
        for (int k = 0; k < 3; k++) {
            webs[k] = newWeb();
            webs[k].setVisibility(View.GONE);
            pages.addView(webs[k], new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
        // 끌어내려 새로고침 표시: 페이지 위쪽 가운데, 평소에는 위로 숨어 있음
        pullDot = new FrameLayout(this);
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(0xFFFFFFFF);
        pullDot.setBackground(dot);
        pullDot.setElevation(dp(4));
        pullIcon = new ImageView(this);
        pullIcon.setImageResource(R.drawable.ic_refresh);
        pullIcon.setColorFilter(getColor(R.color.ink));
        pullIcon.setPadding(dp(9), dp(9), dp(9), dp(9));
        pullDot.addView(pullIcon, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        pages.addView(pullDot, new FrameLayout.LayoutParams(dp(40), dp(40), Gravity.TOP | Gravity.CENTER_HORIZONTAL));
        pullDot.setTranslationY(-dp(48));
        pullDot.setVisibility(View.INVISIBLE);
        web = webs[TAB_HOME];
        root.addView(pages, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        return root;
    }

    private WebView newWeb() {
        WebView w = new WebView(this);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);           // 페이지들이 localStorage를 씀
        s.setUserAgentString(s.getUserAgentString() + " LedgerNotifyApp/" + Updater.ownVersionName(this));
        w.addJavascriptInterface(new Bridge(), "LedgerApp");
        w.setWebViewClient(new Client());
        w.setWebChromeClient(new Chrome());
        w.setOverScrollMode(View.OVER_SCROLL_NEVER);   // 맨 위에서 끌 때는 새로고침 표시만
        w.setOnTouchListener(this::onWebTouch);
        w.setDownloadListener((url, ua, disposition, mime, length) -> {
            if (url.contains("/api/ledger/app.apk")) {
                // 앱 안에서는 받지 않고 바로 새 버전 확인·설치
                toast("새 버전을 확인할게요");
                checkUpdate(false);
            } else {
                openOutside(Uri.parse(url));
            }
        });
        return w;
    }

    /** 위쪽 탭 하나: 아이콘 위·이름 아래 (페이지들의 아래 메뉴와 같은 모양), 고른 탭은 아래에 검정 밑줄 */
    private View tabButton(int which, String label, int icon) {
        FrameLayout f = new FrameLayout(this);
        TypedValue tv = new TypedValue();
        getTheme().resolveAttribute(android.R.attr.selectableItemBackgroundBorderless, tv, true);
        f.setBackgroundResource(tv.resourceId);
        LinearLayout b = new LinearLayout(this);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setGravity(Gravity.CENTER);
        ImageView i = new ImageView(this);
        i.setImageResource(icon);
        b.addView(i, new LinearLayout.LayoutParams(dp(22), dp(22)));
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        t.setGravity(Gravity.CENTER);
        t.setPadding(0, dp(2), 0, 0);
        b.addView(t);
        f.addView(b, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        View line = new View(this);
        line.setBackgroundColor(getColor(R.color.ink));
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dp(40), dp(3), Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        f.addView(line, lp);
        tabLines[which] = line;
        f.setContentDescription(label);
        f.setOnClickListener(v -> {
            // 보고 있는 탭을 다시 누르면 그 페이지 맨 위로
            if (tab == which) web.evaluateJavascript("window.scrollTo({top: 0, behavior: 'smooth'})", null);
            else selectTab(which);
        });
        tabIcons[which] = i;
        tabLabels[which] = t;
        return f;
    }

    /** 위쪽 새로고침 버튼·끌어내려 새로고침: 보고 있는 탭을 다시 읽음 */
    private void refreshTab() {
        loadFailed = false;
        if (loadedSite.isEmpty()) onResume();
        else if (loaded[tab].isEmpty()) load(tab, null);
        else web.reload();
    }

    // ==========================================
    // 좌우로 밀어 탭 넘기기 · 끌어내려 새로고침 (1.30부터).
    // 1.31부터 탭 넘기기는 손가락을 따라감: 가로로 조금 밀면 지금 화면이 손가락을 따라 옆으로, 옆 탭이 반대쪽에서 따라 들어옴
    // (그동안 페이지는 위아래로 스크롤하지 않음). 놓을 때 폭의 30% 넘게 밀었거나 빠르게 튕겼으면 끝까지, 아니면 제자리로.
    // 끝 탭에서는 살짝 끌리다 돌아옴. 새로고침은 손가락 움직임만 보고 페이지에는 그대로 넘김
    // ==========================================
    private float downRawX, downRawY;
    private boolean dragging, settling;
    private int dragStep, dragTo = -1;       // 왼쪽으로 밀면 1(오른쪽 탭), 오른쪽으로 밀면 -1. dragTo: 들어오는 탭 (끝이면 -1)
    private float dragOff;
    private android.view.VelocityTracker velocity;

    private boolean onWebTouch(View v, MotionEvent e) {
        if (settling) return true;               // 넘어가는 애니메이션 중에는 잠깐 받지 않음
        if (v != web) return false;
        if (velocity != null) {
            MotionEvent raw = MotionEvent.obtain(e);
            raw.setLocation(e.getRawX(), e.getRawY());   // 화면이 움직여도 손가락 자리는 화면 기준으로
            velocity.addMovement(raw);
            raw.recycle();
        }
        float dx = e.getRawX() - downRawX, dy = e.getRawY() - downRawY;
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN: {
                downX = e.getX();
                downY = e.getY();
                downRawX = e.getRawX();
                downRawY = e.getRawY();
                downAt = e.getEventTime();
                tracking = true;
                pulling = false;
                dragging = false;
                gestureOk = null;
                if (velocity != null) velocity.recycle();
                velocity = android.view.VelocityTracker.obtain();
                float d = getResources().getDisplayMetrics().density;
                web.evaluateJavascript("window.appGesture ? window.appGesture(" + (downX / d) + ", " + (downY / d) + ") : ''",
                        r -> gestureOk = r == null ? "" : r);
                return false;
            }
            case MotionEvent.ACTION_POINTER_DOWN:   // 두 손가락(확대 등)이면 하지 않음
                if (dragging) return true;
                tracking = false;
                if (pulling) endPull(false);
                return false;
            case MotionEvent.ACTION_MOVE: {
                if (dragging) {
                    moveDrag(dx);
                    return true;
                }
                if (!tracking) return false;
                if (pulling) {
                    showPull(dy);
                    return false;
                }
                String ok = gestureOk;
                if (ok == null) return false;    // 페이지의 답을 기다리는 중
                if (!refreshing && ok.contains("v") && web.getScrollY() == 0 && dy > dp(16) && dy > Math.abs(dx) * 2) {
                    pulling = true;
                    showPull(dy);
                    return false;
                }
                if (Math.abs(dx) > dp(16) && Math.abs(dx) > Math.abs(dy) * 1.5f && (ok.contains("h") || (ok.contains("r") && dx > 0))) {
                    startDrag(e, dx);
                    return true;
                }
                return false;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL: {
                boolean up = e.getActionMasked() == MotionEvent.ACTION_UP, wasDrag = dragging;
                tracking = false;
                if (dragging) {
                    float vx = 0;
                    if (velocity != null) {
                        velocity.computeCurrentVelocity(1000);
                        vx = velocity.getXVelocity();
                    }
                    boolean fling = dragStep == 1 ? vx < -dp(700) : vx > dp(700);
                    endDrag(up && dragTo >= 0 && (Math.abs(dragOff) > pages.getWidth() * 0.3f || fling));
                } else if (pulling) {
                    endPull(up && dy * 0.5f >= dp(PULL_GO));
                }
                if (velocity != null) {
                    velocity.recycle();
                    velocity = null;
                }
                return wasDrag;   // 페이지는 이미 touchcancel을 받음: 손을 뗀 것도 넘기지 않음 (누르기로 잡히지 않게)
            }
        }
        return false;
    }

    /** 옆 탭 (step 1: 오른쪽, -1: 왼쪽), 끝이면 -1 */
    private int neighborTab(int step) {
        int i = 0;
        for (int k = 0; k < ORDER.length; k++) if (ORDER[k] == tab) i = k;
        int j = i + step;
        return j < 0 || j >= ORDER.length ? -1 : ORDER[j];
    }

    /** 탭 넘기기 시작: 페이지에는 손가락이 떨어졌다고 알리고(touchcancel, 위아래 스크롤·줄 밀기 멈춤), 옆 탭을 옆에 붙여 보임 */
    private void startDrag(MotionEvent e, float dx) {
        dragging = true;
        dragStep = dx < 0 ? 1 : -1;
        dragTo = neighborTab(dragStep);
        downRawX += dragStep == 1 ? -dp(16) : dp(16);   // 끌기 시작한 자리부터 따라가게
        MotionEvent cancel = MotionEvent.obtain(e);
        cancel.setAction(MotionEvent.ACTION_CANCEL);
        web.onTouchEvent(cancel);
        cancel.recycle();
        if (dragTo >= 0) {
            if (loaded[dragTo].isEmpty()) load(dragTo, null);   // 처음 보는 탭이면 미리 읽기 시작
            webs[dragTo].setVisibility(View.VISIBLE);
        }
        moveDrag(e.getRawX() - downRawX);
    }

    private void moveDrag(float dx) {
        float off = dragStep == 1 ? Math.min(0, dx) : Math.max(0, dx);   // 시작한 방향으로만
        if (dragTo < 0) off *= 0.25f;                                       // 끝 탭: 살짝 끌리기만
        dragOff = off;
        web.setTranslationX(off);
        if (dragTo >= 0) webs[dragTo].setTranslationX(off + dragStep * pages.getWidth());
    }

    /** 놓음: go면 끝까지 밀고 그 탭으로, 아니면 제자리로 */
    private void endDrag(boolean go) {
        dragging = false;
        int w = pages.getWidth(), to = dragTo, step = dragStep;
        WebView from = web, in = to >= 0 ? webs[to] : null;
        float left = go ? w - Math.abs(dragOff) : Math.abs(dragOff);
        long ms = Math.max(120, Math.min(260, (long) (left / Math.max(1, w) * 320)));
        settling = true;
        from.animate().translationX(go ? -step * w : 0).setDuration(ms).start();
        Runnable done = () -> {
            settling = false;
            from.setTranslationX(0);
            if (in != null) in.setTranslationX(0);
            if (go) selectTab(to);
            else if (in != null && in != web) in.setVisibility(View.GONE);
        };
        if (in != null) in.animate().translationX(go ? 0 : step * w).setDuration(ms).withEndAction(done).start();
        else ui.postDelayed(done, ms);
    }

    /** 끄는 동안: 손가락의 절반만큼 내려오고, 새로고침이 될 만큼 내려오면 진하게 */
    private void showPull(float dy) {
        float p = Math.min(dy * 0.5f, dp(PULL_GO + 40));
        pullDot.animate().cancel();
        pullDot.setVisibility(View.VISIBLE);
        pullDot.setTranslationY(p - dp(48));
        pullIcon.setRotation(p * 2);
        pullDot.setAlpha(p >= dp(PULL_GO) ? 1f : 0.5f + 0.5f * p / dp(PULL_GO));
    }

    /** 놓음: 충분히 끌었으면 표시를 돌리며 새로 읽고(다 읽으면 stopRefresh), 아니면 다시 숨김 */
    private void endPull(boolean go) {
        pulling = false;
        if (!go) {
            hidePull();
            return;
        }
        refreshing = true;
        pullDot.setAlpha(1f);
        pullDot.animate().translationY(dp(16)).setDuration(150).start();
        pullSpin = android.animation.ObjectAnimator.ofFloat(pullIcon, View.ROTATION, pullIcon.getRotation(), pullIcon.getRotation() + 360);
        pullSpin.setDuration(800);
        pullSpin.setRepeatCount(android.animation.ValueAnimator.INFINITE);
        pullSpin.setInterpolator(new android.view.animation.LinearInterpolator());
        pullSpin.start();
        refreshTab();
        ui.postDelayed(this::stopRefresh, 10000);   // 답이 없어도 10초 뒤에는 숨김
    }

    private void stopRefresh() {
        if (!refreshing) return;
        refreshing = false;
        if (pullSpin != null) pullSpin.cancel();
        hidePull();
    }

    private void hidePull() {
        pullDot.animate().translationY(-dp(48)).alpha(0f).setDuration(180)
                .withEndAction(() -> { if (!pulling && !refreshing) pullDot.setVisibility(View.INVISIBLE); }).start();
    }

    /** 그 탭의 웹 화면에 페이지를 엶 (path가 null이면 그 탭의 첫 페이지) */
    private void load(int which, String url) {
        if (loadedSite.isEmpty()) return;
        loaded[which] = url != null ? url : Store.origin(loadedSite) + PATHS[which];
        freshLoad[which] = true;   // 다 읽으면 그 탭의 이전 기록을 지움 (onPageFinished)
        webs[which].loadUrl(loaded[which]);
    }

    /** 탭 바꾸기: 떠나는 페이지에 알리고(근무표 고치기 끝), 그 탭의 웹 화면을 보임 (처음 볼 때 엶) */
    private void selectTab(int which) {
        if (which != TAB_LEDGER && which != TAB_DUTY) which = TAB_HOME;
        if (tab == which) return;
        if (tab >= 0) webs[tab].evaluateJavascript("window.appTabHidden && window.appTabHidden()", null);
        stopRefresh();
        tab = which;
        web = webs[tab];
        for (int k = 0; k < 3; k++) {
            webs[k].setVisibility(k == tab ? View.VISIBLE : View.GONE);
            int color = getColor(k == tab ? R.color.ink : R.color.tab_dim);   // 고른 탭은 검정 + 밑줄, 나머지는 회색
            tabIcons[k].setColorFilter(color);
            tabLabels[k].setTextColor(color);
            tabLabels[k].setTypeface(k == tab ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
            tabLines[k].setVisibility(k == tab ? View.VISIBLE : View.INVISIBLE);
        }
        if (loaded[tab].isEmpty()) load(tab, null);
        // 다른 탭에서 로그인했는데 이 탭은 아직 로그인 화면이면 다시 읽음 (로그인은 탭들이 함께 씀). 홈은 늘 새 요약으로
        else web.evaluateJavascript("(function(){var a=document.getElementById('auth');if(a&&!a.hidden)location.reload();"
                + "else if(window.homeRefresh)window.homeRefresh();})()", null);
        loadFailed = false;
        progress.setVisibility(View.GONE);
        showBanner();
    }

    /** 할 일 한 줄: 알림 읽기 권한 → 페이지를 못 엶 → 알림 권한(금액 인식 알림) → 새 버전 설치 허용 → 앱 연결 순서로 하나만 */
    private void showBanner() {
        if (banner == null) return;
        String text = null;
        View.OnClickListener go = null;
        if (store.site().isEmpty()) {
            text = "가계부 주소를 넣어 주세요 — 눌러서 설정";
            go = v -> openSettings(SettingsActivity.SECTION_APP);
        } else if (loadFailed) {
            text = "페이지를 열지 못했어요 — 인터넷·가계부 주소를 확인하고 눌러서 다시";
            go = v -> { loadFailed = false; showBanner(); web.reload(); };
        } else if (!SettingsActivity.hasAccess(this)) {
            text = "알림 읽기 권한이 꺼져 있어 결제 알림을 못 받아요 — 눌러서 켜기";
            go = v -> openSettings(SettingsActivity.SECTION_PHONE);
        } else if (store.alertOn() && store.askedNotifyPermission() && !Notifier.allowed(this)) {
            text = "알림 권한이 꺼져 있어 금액 인식 알림을 못 띄워요 — 눌러서 켜기 (설정에서 이 알림을 끌 수도 있어요)";
            go = v -> startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        } else if (updateNeedsPermission && !getPackageManager().canRequestPackageInstalls()) {
            text = "새 버전이 있어요 — 눌러서 '이 앱의 설치 허용' 켜기";
            go = v -> startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())));
        } else if (updateText.contains("설치 중") || updateText.contains("받는 중")) {
            text = updateText;
        } else if (store.url().isEmpty() && tab == TAB_LEDGER) {
            text = "결제 알림이 아직 가계부로 안 가요 — 위쪽 '설정' → 결제 알림 연결 → '이 휴대폰 앱에 연결'을 누르세요";
        }
        banner.setText(text == null ? "" : text);
        banner.setOnClickListener(go);
        banner.setVisibility(text == null ? View.GONE : View.VISIBLE);
    }

    // ==========================================
    // 웹 화면
    // ==========================================
    private boolean sameSite(Uri u) {
        return Store.origin(u.toString()).equals(Store.origin(loadedSite));
    }

    /** 주소가 어느 탭의 페이지인지 (-1: 앱의 페이지가 아님) */
    private static int tabOf(Uri u) {
        String path = u.getPath() == null ? "" : u.getPath();
        for (int k = 0; k < 3; k++) {
            String p = PATHS[k];
            if (path.equals(p.substring(0, p.length() - 1)) || path.startsWith(p)) return k;
        }
        return -1;
    }

    private void openOutside(Uri u) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (ActivityNotFoundException e) {
            toast("열 수 있는 앱이 없어요");
        }
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!sameSite(u)) {
                openOutside(u);
                return true;
            }
            int target = tabOf(u);
            if (target < 0) {
                if ((u.getPath() == null ? "" : u.getPath()).startsWith("/api/ledger/")) return false;
                // 앱에서는 홈·가계부·근무표만: 같은 사이트라도 그 밖(대시보드·동영상 등)으로는 가지 않음
                toast("앱에서는 가계부·근무표만 볼 수 있어요");
                return true;
            }
            if (view == webs[target]) return false;
            // 다른 탭의 페이지(홈 카드, 근무표 로그인 화면의 '가계부에서 가입' 등)는 그 탭에서
            boolean inbox = target == TAB_LEDGER && "inbox".equals(u.getFragment());
            if (inbox && !loaded[TAB_LEDGER].isEmpty()) {
                webs[TAB_LEDGER].evaluateJavascript("window.appShowInbox && window.appShowInbox()", null);
            } else if (inbox || loaded[target].isEmpty() || u.getQuery() != null) {
                load(target, u.toString());
            }
            selectTab(target);
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            pageOrigin = Store.origin(url);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            for (int k = 0; k < 3; k++) if (webs[k] == view && freshLoad[k]) { freshLoad[k] = false; view.clearHistory(); }
            if (view == web) stopRefresh();
            showBanner();
            DutyPush.sync(MainActivity.this);
            if (view == webs[TAB_LEDGER]) scrollToInbox();
            if (view == webs[TAB_DUTY]) {
                dutyLoaded = true;
                openDutyDay();
            }
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (!req.isForMainFrame()) return;
            // 못 연 탭은 다음에 그 탭을 볼 때 다시 엶 (앱을 켤 때 인터넷이 잠깐 끊겼던 경우 등)
            for (int k = 0; k < 3; k++) if (webs[k] == view) loaded[k] = "";
            if (view == web) {
                stopRefresh();
                loadFailed = true;
                showBanner();
            }
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int p) {
            if (view != web) return;
            progress.setProgress(p);
            progress.setVisibility(p < 100 ? View.VISIBLE : View.GONE);
        }

        /** 관리자 칸의 앱 파일 올리기, 가계부 사진 붙이기(사진은 PhotoPick이 JPEG로 바꿔 넘김) 등 <input type=file> */
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = cb;
            fileView = view;
            boolean image = PhotoPick.isImage(params.getAcceptTypes());
            try {
                startActivityForResult(image ? PhotoPick.intent(params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) : params.createIntent(),
                        image ? PICK_PHOTO : PICK_FILE);
                return true;
            } catch (ActivityNotFoundException e) {
                fileCallback = null;
                return false;
            }
        }
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        if (req == PICK_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
            return;
        }
        if (req == PICK_PHOTO && fileCallback != null) {
            ValueCallback<Uri[]> cb = fileCallback;
            fileCallback = null;
            java.util.List<Uri> picked = result == RESULT_OK ? PhotoPick.uris(data) : new java.util.ArrayList<>();
            if (picked.isEmpty()) { cb.onReceiveValue(null); return; }
            // 바꾸는 동안 맨 위 진행 막대 + 안내 (1.29부터), 넘긴 뒤 페이지를 다시 그림 (앱 안 화면이 사진을 받고도 그대로이던 것)
            WebView page = fileView;
            progress.setIndeterminate(true);
            progress.setVisibility(View.VISIBLE);
            toast("사진 준비 중…");
            new Thread(() -> {
                Uri[] out = PhotoPick.toJpegs(this, picked);
                ui.post(() -> {
                    progress.setIndeterminate(false);
                    progress.setVisibility(View.GONE);
                    cb.onReceiveValue(out);
                    if (page == null) return;
                    for (long ms : new long[]{0, 300, 1000, 2500}) ui.postDelayed(() -> {
                        page.invalidate();
                        page.evaluateJavascript("window.appPhotosArrived && window.appPhotosArrived()", null);
                    }, ms);
                });
            }, "photo-pick").start();
            return;
        }
        super.onActivityResult(req, result, data);
    }

    /** 페이지들이 부르는 것 (window.LedgerApp). 가계부 주소의 페이지에서만 받음 */
    private class Bridge {
        private boolean fromLedger() {
            return !loadedSite.isEmpty() && pageOrigin.equals(Store.origin(loadedSite));
        }

        @JavascriptInterface
        public String version() {
            return Updater.ownVersionName(MainActivity.this);
        }

        /** 이 앱이 지금 이 가계부로 결제 알림을 보내고 있는지 */
        @JavascriptInterface
        public boolean connected() {
            String u = store.url();
            return fromLedger() && !u.isEmpty() && Store.origin(u).equals(pageOrigin);
        }

        /** 가계부에서 만든 연결 주소를 받음 (같은 가계부 주소의 /api/ledger/hook/…만) */
        @JavascriptInterface
        public boolean connect(String url) {
            if (!fromLedger() || url == null) return false;
            String prefix = pageOrigin + "/api/ledger/hook/";
            if (!url.toLowerCase(java.util.Locale.ROOT).startsWith(prefix) || url.length() < prefix.length() + 10) return false;
            store.setUrl(url);
            ui.post(() -> {
                showBanner();
                toast("이 앱에 연결했어요 — 이제 결제 알림이 확인 대기함으로 가요");
            });
            return true;
        }

        /** 로그인됨: 로그인 전이라 새 버전을 확인하지 못했으면 바로 다시 */
        @JavascriptInterface
        public void loggedIn() {
            if (!fromLedger()) return;
            ui.post(() -> {
                CookieManager.getInstance().flush();
                DutyPush.sync(MainActivity.this);
                if (Updater.NEED_LOGIN.equals(updateText)) {
                    updateText = "";
                    MainActivity.this.checkUpdate(true);
                }
            });
        }

        /** 근무표 페이지에서 근무·사람·근무 종류를 고쳐 저장함: 홈 화면 위젯을 새로 */
        @JavascriptInterface
        public void dutyChanged() {
            if (!fromLedger()) return;
            CookieManager.getInstance().flush();
            DutyWidgets.refreshAll(MainActivity.this);
        }

        /** 근무표 설정 > 이 휴대폰 > 처음 보일 사람: 새로 놓는 위젯에서 먼저 보임 */
        @JavascriptInterface
        public void setDutyPerson(int personId) {
            if (!fromLedger()) return;
            DutyWidgets.setDefaultPerson(MainActivity.this, personId);
        }

        /** 가계부 설정의 '휴대폰 알림 설정 열기': 알림 읽기 권한·연결 주소·무시할 알림·최근 알림 */
        @JavascriptInterface
        public void openPhoneSettings() {
            ui.post(() -> MainActivity.this.openSettings(SettingsActivity.SECTION_PHONE));
        }

        /** 홈 > 설정의 결제 알림 줄 하나 (1.13부터): access·link·ignore·apps·logs 중 그 칸만 보이는 화면 */
        @JavascriptInterface
        public void openPhoneSection(String section) {
            if (!fromLedger()) return;
            String s = SettingsActivity.ONE_SECTIONS.contains(section) ? section : SettingsActivity.SECTION_PHONE;
            ui.post(() -> MainActivity.this.openSettings(s));
        }

        /** 전체 설정의 '새 버전 확인' (결과는 updateText로 물어봄) */
        @JavascriptInterface
        public void checkUpdate() {
            if (!fromLedger()) return;
            ui.post(() -> MainActivity.this.checkUpdate(false));
        }

        @JavascriptInterface
        public String updateText() {
            return updateText;
        }

        /** 전체 설정에서 로그아웃함: 가계부·근무표 탭도 다시 읽음 */
        @JavascriptInterface
        public void loggedOut() {
            if (!fromLedger()) return;
            ui.post(() -> {
                CookieManager.getInstance().flush();
                for (int k = 0; k < 3; k++) if (k != tab && !loaded[k].isEmpty()) webs[k].reload();
            });
        }

        /** 가계부 설정 > 버린 알림의 '이런 알림 안 받기': 그 알림 글로 낱말 고르기 창 (무시할 알림 설정 화면 위에) */
        @JavascriptInterface
        public void pickIgnore(String text) {
            if (!fromLedger() || text == null || text.trim().isEmpty()) return;
            String t = text.length() > 300 ? text.substring(0, 300) : text;
            ui.post(() -> startActivity(new Intent(MainActivity.this, SettingsActivity.class)
                    .putExtra(SettingsActivity.EXTRA_SECTION, SettingsActivity.SECTION_IGNORE)
                    .putExtra(SettingsActivity.EXTRA_IGNORE_TEXT, t)));
        }

        /** 홈 > 설정의 '결제 알림 (이 휴대폰)': 알림 읽기 권한·배터리·금액 인식 알림·무시할 알림 수·연결 */
        @JavascriptInterface
        public String phoneState() {
            if (!fromLedger()) return "{}";
            try {
                android.os.PowerManager pm = getSystemService(android.os.PowerManager.class);
                return new org.json.JSONObject()
                        .put("access", SettingsActivity.hasAccess(MainActivity.this))
                        .put("battery", pm != null && pm.isIgnoringBatteryOptimizations(getPackageName()))
                        .put("alertOn", store.alertOn())
                        .put("ignores", store.ignores().size())
                        .put("connected", !store.url().isEmpty())
                        .put("dutyPush", DutyPush.available(MainActivity.this) ? store.dutyPushOn() : null)
                        .put("ledgerPush", DutyPush.available(MainActivity.this) ? store.ledgerPushOn() : null)
                        .put("notifyAllowed", Notifier.allowed(MainActivity.this))
                        .toString();
            } catch (org.json.JSONException e) {
                return "{}";
            }
        }

        /** 홈 > 설정의 '금액 인식 알림' 켜고 끄기 (켤 때 알림 권한이 없으면 앱의 결제 알림 화면으로) */
        @JavascriptInterface
        public void setAlertOn(boolean on) {
            if (!fromLedger()) return;
            store.setAlertOn(on);
            if (on && !Notifier.allowed(MainActivity.this)) ui.post(() -> MainActivity.this.openSettings(SettingsActivity.SECTION_PHONE));        }

        /** 홈 > 설정의 '근무표 변경 알림' 켜고 끄기 (끄면 서버에서 이 휴대폰 토큰을 지움, 켤 때 알림 권한이 없으면 물음) */
        @JavascriptInterface
        public void setDutyPushOn(boolean on) {
            if (!fromLedger() || on == store.dutyPushOn()) return;
            store.setDutyPushOn(on);
            pushChanged(on);
        }

        /** 홈 > 설정의 '가계부 변경 알림' 켜고 끄기 (1.14부터) */
        @JavascriptInterface
        public void setLedgerPushOn(boolean on) {
            if (!fromLedger() || on == store.ledgerPushOn()) return;
            store.setLedgerPushOn(on);
            pushChanged(on);
        }

        /** 켜거나 끈 것을 서버에 알리고, 켰는데 알림 권한이 없으면 물음 */
        private void pushChanged(boolean on) {
            DutyPush.changed(MainActivity.this);
            if (on && !Notifier.allowed(MainActivity.this)) ui.post(() -> {
                if (android.os.Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 3);
                else startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName()));
            });
        }

        /** 근무표 설정 > 구글 캘린더 (1.16부터): {on, allowed, calendars:[{id, name, account, color, shown}]} */
        @JavascriptInterface
        public String calendarState() {
            if (!fromLedger()) return "{}";
            try {
                return new org.json.JSONObject().put("on", store.calendarOn())
                        .put("allowed", PhoneCalendar.allowed(MainActivity.this))
                        .put("calendars", PhoneCalendar.calendars(MainActivity.this, store.calendarHidden())).toString();
            } catch (org.json.JSONException e) {
                return "{}";
            }
        }

        /** 캘린더 일정 보이기 켜고 끄기 (켤 때 권한이 없으면 물음) */
        @JavascriptInterface
        public void setCalendarOn(boolean on) {
            if (!fromLedger()) return;
            store.setCalendarOn(on);
            ui.post(() -> {
                if (on && !PhoneCalendar.allowed(MainActivity.this)) MainActivity.this.askCalendar();
                else calendarChanged();
            });
        }

        /** 권한이 꺼져 있을 때 '허용하기' */
        @JavascriptInterface
        public void askCalendar() {
            if (!fromLedger()) return;
            ui.post(MainActivity.this::askCalendar);
        }

        /** 캘린더 하나 보이기·숨기기 */
        @JavascriptInterface
        public void setCalendarShown(String id, boolean shown) {
            if (!fromLedger() || id == null) return;
            store.setCalendarShown(id, shown);
        }

        /** from~to(yyyy-MM-dd) 일정 (PhoneCalendar.events). 꺼져 있거나 권한이 없으면 "null" */
        @JavascriptInterface
        public String calendarEvents(String from, String to) {
            if (!fromLedger() || !store.calendarOn() || !PhoneCalendar.allowed(MainActivity.this)) return "null";
            try {
                return PhoneCalendar.events(MainActivity.this, from, to, store.calendarHidden()).toString();
            } catch (org.json.JSONException e) {
                return "null";
            }
        }

        @JavascriptInterface
        public void openSettings() {
            ui.post(() -> MainActivity.this.openSettings(SettingsActivity.SECTION_PHONE));
        }
    }

    // ==========================================
    // 도우미
    // ==========================================
    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }
}
