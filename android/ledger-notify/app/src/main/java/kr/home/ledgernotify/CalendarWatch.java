package kr.home.ledgernotify;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.provider.CalendarContract;

/**
 * 휴대폰 캘린더가 바뀌면(일정을 넣거나 고침, 구글 계정 동기화) 근무표 위젯을 곧 다시 그림 (1.18부터).
 * 앱이 꺼져 있어도 시스템이 캘린더 변경을 보고 깨워 줌 (JobScheduler 내용 변경 트리거). 한 번 깨우면 끝나서 그릴 때마다 다시 걸어 둠.
 * 위젯이 없거나 근무표 설정 > 구글 캘린더를 껐거나 권한이 없으면 걸지 않음
 */
public class CalendarWatch extends JobService {
    private static final int JOB_ID = 7100;

    static void schedule(Context c) {
        JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        if (!new Store(c).calendarOn() || !PhoneCalendar.allowed(c) || !DutyWidgets.any(c)) {
            js.cancel(JOB_ID);
            return;
        }
        if (js.getPendingJob(JOB_ID) != null) return;
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(c, CalendarWatch.class))
                .addTriggerContentUri(new JobInfo.TriggerContentUri(CalendarContract.CONTENT_URI,
                        JobInfo.TriggerContentUri.FLAG_NOTIFY_FOR_DESCENDANTS))
                .setTriggerContentUpdateDelay(5000)      // 동기화로 여러 번 바뀌면 조용해진 뒤 한 번
                .setTriggerContentMaxDelay(60000)
                .build();
        try {
            js.schedule(job);
        } catch (RuntimeException ignored) {
            // 걸지 못해도 3시간마다·자정·앱을 닫을 때 새로 그림
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            try {
                DutyWidgets.redrawAll(this);   // 저장해 둔 근무표 + 새 일정 (다시 걸어 둠)
            } finally {
                jobFinished(params, false);
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return false;
    }
}
