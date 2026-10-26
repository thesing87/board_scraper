"""모든 테스트를 차례로 실행하고 결과를 요약.

    python tests/run_tests.py              전체
    python tests/run_tests.py e2e_ sim_    이름이 이 접두어로 시작하는 테스트만
    python tests/run_tests.py --offline    실제 사이트(LIVE_URL)가 필요한 테스트 제외

테스트 파일은 각각 독립 실행되는 스크립트이며, assert 실패나 예외가 나면 0이 아닌 종료 코드로 끝남.
"""
import os
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    args = sys.argv[1:]
    offline = '--offline' in args
    prefixes = [a for a in args if not a.startswith('--')]
    names = sorted(n for n in os.listdir(TESTS_DIR)
                   if n.endswith('.py') and n.startswith(('test_', 'sim_', 'e2e_'))
                   and (not prefixes or n.startswith(tuple(prefixes))))
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    results = []
    for name in names:
        path = os.path.join(TESTS_DIR, name)
        if offline and 'LIVE_URL' in open(path, encoding='utf-8').read().replace('from common import ROOT, DATA_DIR, LIVE_URL, shot_dir', ''):
            results.append((name, 'SKIP', 0, '실제 사이트 필요'))
            continue
        started = time.time()
        proc = subprocess.run([sys.executable, '-B', '-X', 'utf8', path], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', env=env, cwd=TESTS_DIR)
        output = (proc.stdout + proc.stderr).strip().splitlines()
        last = next((line for line in reversed(output) if line.strip()), '')
        status = 'PASS' if proc.returncode == 0 else 'FAIL'
        results.append((name, status, time.time() - started, last[:120]))
        print(f"{status}  {name:24s} {time.time() - started:5.1f}s  {last[:100]}", flush=True)
        if status == 'FAIL':
            print('      ' + '\n      '.join(output[-12:]), flush=True)
    failed = [r for r in results if r[1] == 'FAIL']
    skipped = [r for r in results if r[1] == 'SKIP']
    print(f"\n통과 {len(results) - len(failed) - len(skipped)} · 실패 {len(failed)} · 건너뜀 {len(skipped)}")
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    main()
