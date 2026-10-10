"""Move the tool bay to a column on the right of the office. Run once from the project folder: python upgrade_u7.py

Every piece is matched exactly once before anything is written, so a mismatch changes nothing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
problems = []


def swap(text, old, new, label):
    if text.count(old) != 1:
        problems.append(f"{label} (found {text.count(old)} times)")
        return text
    return text.replace(old, new)


office = (ROOT / "static/office.js").read_text(encoding="utf-8")

office = swap(office, r'''  const W = 640;
''', r'''  const DESK_W = 640; // the desks and the back wall decorations
  const W = 760; // 640 for the desks plus a 120 wide tool column on the right
''', "office.js #1")

office = swap(office, r'''  const contentHeight = () => TOP + 26 + rowCount() * ROW_H + BAY_H + 6;''',
r'''  const contentHeight = () => Math.max(TOP + 26 + rowCount() * ROW_H + 6, bayBottom());''', "office.js #2")

office = swap(office, r'''      rect(40, y, W - 80, ROW_H - 12, alpha("#8c7cf6", 0.07));''',
r'''      rect(40, y, DESK_W - 80, ROW_H - 12, alpha("#8c7cf6", 0.07));''', "office.js #3")

office = swap(office, r'''  const bayTop = () => TOP + 26 + rowCount() * ROW_H + 2;
  const brainPos = () => ({ x: 96, y: bayTop() });''', r'''  const COL_X = 690; // the tool column on the right: the Brain on top, one station under another
  const STATION_STEP = 56;
  const bayTop = () => TOP + 36;
  const brainPos = () => ({ x: COL_X, y: bayTop() });
  function bayBottom() {
    const n = presentStations().length;
    return bayTop() + (n ? 58 + (n - 1) * STATION_STEP : 0) + 52 + 8;
  }''', "office.js #4")

office = swap(office, r'''    return { x: 196 + Math.max(0, i) * 92, y: bayTop() };''',
r'''    return { x: COL_X, y: bayTop() + 58 + Math.max(0, i) * STATION_STEP };''', "office.js #5")

office = swap(office, r'''    rect(40, y - 2, W - 80, BAY_H - 6, alpha("#4da3ff", 0.045));
    rect(40, y - 2, W - 80, 1, alpha("#8c7cf6", 0.35));
    text("TOOL BAY", W - 46, y + 6, "#6f6e98", 6, "right");''', r'''    const left = DESK_W + 8, bottom = bayBottom();
    rect(left, y - 14, W - left - 8, bottom - y + 14, alpha("#4da3ff", 0.045));
    rect(left, y - 14, W - left - 8, 1, alpha("#8c7cf6", 0.35));
    text("TOOL BAY", COL_X, y - 4, "#6f6e98", 6);''', "office.js #6")

office = swap(office, r'''    const loungeY = TOP + 26 + rowCount() * ROW_H + BAY_H;''',
r'''    const loungeY = TOP + 26 + rowCount() * ROW_H;''', "office.js #7")

office = swap(office, r'''    drawPlant(W - 20, H - 18);''', r'''    drawPlant(DESK_W - 20, H - 18);''', "office.js #8")

office = swap(office, r'''    const top = bayTop();
    if (p.y > top - 4 && p.y < top + 52) {
      const b = brainPos();
      if (Math.abs(p.x - b.x) < 34) return { kind: "brain" };
      for (const key of presentStations()) if (Math.abs(p.x - stationPos(key).x) < 24) return { kind: "station", key };
    }''', r'''    const b = brainPos();
    if (Math.abs(p.x - b.x) < 34 && p.y > b.y - 4 && p.y < b.y + 52) return { kind: "brain" };
    for (const key of presentStations()) {
      const s = stationPos(key);
      if (Math.abs(p.x - s.x) < 28 && p.y > s.y - 4 && p.y < s.y + 52) return { kind: "station", key };
    }''', "office.js #9")

office = swap(office, r'''text("Nobody works here yet", W / 2, TOP + 80''', r'''text("Nobody works here yet", DESK_W / 2, TOP + 80''', "office.js #10")

if problems:
    print("Nothing was changed. These pieces did not match:")
    for p in problems:
        print("  -", p)
    raise SystemExit(1)

(ROOT / "static/office.js").write_text(office, encoding="utf-8")
print("Done: the tool bay is now a column on the right.")
