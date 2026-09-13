"""진단용: 저장된 달력 HTML에서 후보 셀 텍스트/속성을 그대로 출력한다.

`umppa-monitor inspect` 가 저장한 page_0.html(달력) 또는 slot_*.html(회차 목록)을
읽어, 우리 파서가 실제로 어떤 요소를 후보로 보는지, 각 요소의 class/attr/원문
텍스트가 무엇인지를 사람이 읽을 수 있게 덤프한다. 실제 사이트 구조를 확인하지
못한 채 작성된 휴리스틱을 실사이트 데이터로 보정하기 위한 1회성 도구.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

from umppa_monitor.parsers.calendar import _candidate_cells, find_year_month
from umppa_monitor.parsers.common import normalize_ws


def main() -> None:
    path = Path(sys.argv[1])
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    print(f"=== FILE: {path} ({len(html)} bytes) ===")
    print("year_month:", find_year_month(soup))

    tables = soup.find_all("table")
    print(f"\n--- tables found: {len(tables)} ---")
    for i, t in enumerate(tables):
        head = normalize_ws(t.get_text(" "))[:100]
        print(f"table#{i} class={t.get('class')} id={t.get('id')} :: {head}")

    cells = _candidate_cells(soup, None)
    print(f"\n--- candidate cells: {len(cells)} ---")
    for i, c in enumerate(cells[:50]):
        cls = c.get("class")
        onclick = c.get("onclick")
        txt = normalize_ws(c.get_text(" "))
        links = [(a.get("class"), a.get("onclick"), a.get("href"), normalize_ws(a.get_text(" ")))
                for a in c.find_all(["a", "button"])]
        print(f"[{i}] class={cls} onclick={onclick!r} text={txt!r} links={links}")

    # 회차/시간/잔여로 보이는 하위 요소도 넓게 훑는다
    print("\n--- elements mentioning 예약/회차/잔여/마감/가능 (최대 60개) ---")
    kws = ("예약", "회차", "잔여", "마감", "가능", "불가", "휴관", "신청", "정원")
    seen = 0
    for el in soup.find_all(True):
        txt = normalize_ws(el.get_text(" "))
        if not txt or len(txt) > 80:
            continue
        if any(k in txt for k in kws):
            # 가장 안쪽 요소만 (자식이 같은 텍스트를 갖고 있으면 스킵)
            if any(normalize_ws(ch.get_text(" ")) == txt for ch in el.find_all(True)):
                continue
            print(f"<{el.name} class={el.get('class')} onclick={el.get('onclick')!r}> {txt!r}")
            seen += 1
            if seen >= 60:
                break


if __name__ == "__main__":
    main()
