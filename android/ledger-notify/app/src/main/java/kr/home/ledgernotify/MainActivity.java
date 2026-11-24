package kr.home.ledgernotify;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
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
 */
public class MainActivity extends Activity {
    private static final int PICK_FILE = 1;
    static final int TAB_LEDGER = 0, TAB_DUTY = 1, TAB_HOME = 2;
    private static final String[] PATHS = {"/ledger/", "/duty/", "/yeye/"};
    /** 이 탭으로 열기 (근무표 위젯을 누름) */
    static final String EXTRA_TAB = "tab";
    /** 앱 설정에서 로그아웃함: 돌아오면 세 페이지를 모두 다시 읽음 */
    static volatile boolean reloadPages;

    private Store store;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;                     // 지금 보이는 탭의 웹 화면
    private final WebView[] webs = new WebView[3];
    private final String[] loaded = {"", "", ""};   // 탭마다 띄운 주소 (가계부 외에는 그 탭을 처음 볼 때 엶)
    private int tab = -1;
    private final TextView[] tabLabels = new TextView[3];
    private final ImageView[] tabIcons = new ImageView[3];
    private final View[] tabLines = new View[3];
    private TextView banner;
    private ProgressBar progress;
    private String loadedSite = "";
    private volatile String pageOrigin = "";
    private ValueCallback<Uri[]> fileCallback;
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
        }
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
        for (WebView w : webs) w.onPause();
        CookieManager.getInstance().flush();   // 가계부 로그인 쿠키를 바로 저장
        // 앱에서 로그인했거나 근무표를 봤으면 위젯도 새로 (위젯이 있을 때만)
        if (DutyWidgets.any(this)) DutyWidgets.refreshAll(this);
    }

    /**
     * 뒤로가기: 페이지에 열린 것(설정·고치기·색 고르기·메모 목록 등)이 있으면 그것부터 닫고,
     * 가계부·근무표 탭이면 홈 탭으로, 홈 탭이면 '한 번 더 누르면 종료' 안내
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

    private void checkUpdate(boolean auto) {
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

        // ---- 위쪽 한 줄: 제목 · 탭(홈 | 가계부 | 근무표, 아이콘 위·이름 아래, 고른 탭은 흰 밑줄) · 새로고침
        // (설정은 각 페이지의 아래 메뉴에, 이 휴대폰의 것도 홈 > 설정. 페이지를 못 열면 위 안내 줄을 눌러 앱 설정)
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(getColor(R.color.green));
        bar.setPadding(dp(14), 0, dp(2), 0);
        TextView title = new TextView(this);
        title.setText(R.string.app_name);   // 시험 앱은 'YeYe홈 테스트'
        title.setTextColor(0xFFFFFFFF);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, 0, dp(10), 0);
        title.setGravity(Gravity.CENTER_VERTICAL);
        title.setIncludeFontPadding(false);
        bar.addView(title, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.MATCH_PARENT));
        bar.addView(tabButton(TAB_HOME, "홈", R.drawable.ic_tab_home), new LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.MATCH_PARENT));
        bar.addView(tabButton(TAB_LEDGER, "가계부", R.drawable.ic_tab_ledger), new LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.MATCH_PARENT));
        bar.addView(tabButton(TAB_DUTY, "근무표", R.drawable.ic_tab_duty), new LinearLayout.LayoutParams(dp(62), ViewGroup.LayoutParams.MATCH_PARENT));
        bar.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
        ImageView refresh = new ImageView(this);
        refresh.setImageResource(R.drawable.ic_refresh);
        refresh.setColorFilter(0xFFFFFFFF);
        refresh.setScaleType(ImageView.ScaleType.CENTER);
        refresh.setContentDescription("새로고침");
        TypedValue rtv = new TypedValue();
        getTheme().resolveAttribute(android.R.attr.selectableItemBackgroundBorderless, rtv, true);
        refresh.setBackgroundResource(rtv.resourceId);
        refresh.setOnClickListener(v -> {
            loadFailed = false;
            if (loadedSite.isEmpty()) onResume();
            else if (loaded[tab].isEmpty()) load(tab, null);
            else web.reload();
        });
        bar.addView(refresh, new LinearLayout.LayoutParams(dp(48), ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56)));

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
        FrameLayout pages = new FrameLayout(this);
        for (int k = 0; k < 3; k++) {
            webs[k] = newWeb();
            webs[k].setVisibility(View.GONE);
            pages.addView(webs[k], new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
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

    /** 위쪽 탭 하나: 아이콘 위·이름 아래 (페이지들의 아래 메뉴와 같은 모양), 고른 탭은 아래에 흰 밑줄 */
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
        line.setBackgroundColor(0xFFFFFFFF);
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

    /** 그 탭의 웹 화면에 페이지를 엶 (path가 null이면 그 탭의 첫 페이지) */
    private void load(int which, String url) {
        if (loadedSite.isEmpty()) return;
        loaded[which] = url != null ? url : Store.origin(loadedSite) + PATHS[which];
        webs[which].loadUrl(loaded[which]);
    }

    /** 탭 바꾸기: 떠나는 페이지에 알리고(근무표 고치기 끝), 그 탭의 웹 화면을 보임 (처음 볼 때 엶) */
    private void selectTab(int which) {
        if (which != TAB_LEDGER && which != TAB_DUTY) which = TAB_HOME;
        if (tab == which) return;
        if (tab >= 0) webs[tab].evaluateJavascript("window.appTabHidden && window.appTabHidden()", null);
        tab = which;
        web = webs[tab];
        for (int k = 0; k < 3; k++) {
            webs[k].setVisibility(k == tab ? View.VISIBLE : View.GONE);
            int color = k == tab ? 0xFFFFFFFF : 0xB3FFFFFF;   // 고른 탭은 흰색 + 밑줄, 나머지는 흐린 흰색
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
            showBanner();
            DutyPush.sync(MainActivity.this);
            if (view == webs[TAB_LEDGER]) scrollToInbox();
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (!req.isForMainFrame()) return;
            // 못 연 탭은 다음에 그 탭을 볼 때 다시 엶 (앱을 켤 때 인터넷이 잠깐 끊겼던 경우 등)
            for (int k = 0; k < 3; k++) if (webs[k] == view) loaded[k] = "";
            if (view == web) {
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

        /** 관리자 칸의 앱 파일 올리기 등 <input type=file> */
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = cb;
            try {
                startActivityForResult(params.createIntent(), PICK_FILE);
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
