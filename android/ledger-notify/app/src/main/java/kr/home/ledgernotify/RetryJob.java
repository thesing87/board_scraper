package kr.home.ledgernotify;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** 인터넷이 다시 되면 못 보낸 알림을 보냄. 그래도 못 보내면 시스템이 간격을 늘려 다시 부름 */
public class RetryJob extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> jobFinished(params, !Sender.flush(this))).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
