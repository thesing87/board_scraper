package kr.home.ledgernotify;

import java.util.regex.Pattern;

/**
 * 결제 알림처럼 보이는 글만 서버로 보냄 (카톡 대화 같은 다른 알림은 휴대폰 밖으로 나가지 않게).
 * 서버(ledger_parse.py)와 같은 기준: 'O원' 금액이 있고 승인·결제·취소 같은 낱말이 있어야 함
 */
final class PayFilter {
    private static final Pattern AMOUNT = Pattern.compile("(?<![\\d,])\\d{1,3}(?:,\\d{3})+\\s*원|(?<![\\d,])\\d+\\s*원");
    private static final String[] WORDS = {"승인", "결제", "사용", "출금", "체크", "일시불", "할부", "이용", "취소", "환불"};

    private PayFilter() { }

    static boolean looksLikePayment(String text) {
        if (text == null || text.length() > 2000 || !AMOUNT.matcher(text).find()) return false;
        for (String w : WORDS) if (text.contains(w)) return true;
        return false;
    }
}
