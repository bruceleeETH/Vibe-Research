const { test } = require('node:test');
const assert = require('node:assert/strict');
const { features, matches, simulate, runStudy, dateSnapshot, reviewDates } = require(process.env.TREND_ENGINE_JS);
const options = { volume: 1.5, stop: 5, days: 3, cost: .2, mode: 'day' };
function sample() {
  const bars = Array.from({ length: 27 }, (_, i) => ({ date: `2026-01-${String(i + 1).padStart(2, '0')}`, open: 100, close: i < 20 ? 90 : 100, high: 101, low: 89, volume: 100 }));
  for (let i = 21; i < bars.length; i++) bars[i].low = 99;
  bars[20].volume = 200;
  return { code: '600869', name: '测试', source_url: '', bars };
}
const calc = (s, o = options) => simulate(s, 20, o, s.bars.map(x => x.date));
const closeOptions = { ...options, entryTiming: 'signal-close' };
test('close entry uses selected date and next trading session for comparison', () => {
  const s = sample(), data = { stocks: [s], start: '2026-01-01', cutoff: '2026-01-27' };
  const r = dateSnapshot(data, '2026-01-21', closeOptions);
  assert.equal(r.entryDate, '2026-01-21'); assert.equal(r.sellDate, '2026-01-22');
  assert.equal(r.rows[0].entry.close, 100);
});
test('close entry ignores pre-entry low and expires on third later session', () => {
  const s = sample(); s.bars[20].open = 92; s.bars[23].close = 104; s.bars[23].high = 105;
  const r = calc(s, closeOptions);
  assert.equal(r.entry, 100); assert.equal(r.exitDate, s.bars[23].date);
  assert.equal(r.exit, 104); assert.ok(Math.abs(r.worst + 1) < 1e-9);
});
test('first day after close entry can gap through stop, not guaranteed minus five', () => {
  const s = sample(); s.bars[21].open = 90; s.bars[21].low = 80;
  const r = calc(s, closeOptions);
  assert.equal(r.exitDate, s.bars[21].date); assert.equal(r.exit, 90);
  assert.ok(Math.abs(r.worst + 10) < 1e-9);
});
test('latest close entry is known but next day prices stay unknown', () => {
  const data = { stocks: [sample()], start: '2026-01-01', cutoff: '2026-01-27' };
  const r = dateSnapshot(data, '2026-01-27', closeOptions);
  assert.equal(r.entryDate, '2026-01-27'); assert.equal(r.sellDate, undefined);
  assert.equal(r.rows[0].sell, undefined);
});
test('volume denominator excludes signal day and future bars', () => {
  const s = sample(); assert.equal(features(s.bars, 20).vr, 2); assert.equal(matches(s.bars, 20, options), true);
  s.bars[21].volume = 1e9; assert.equal(features(s.bars, 20).vr, 2);
});
test('D0 trigger respects T+1, exits next opening, ignores later daily low', () => {
  const s = sample(); s.bars[21].low = 90; s.bars[22].open = 98; s.bars[22].low = 80;
  const r = calc(s); assert.equal(r.exitDate, s.bars[22].date); assert.equal(r.exit, 98); assert.ok(Math.abs(r.worst + 10) < 1e-9);
});
test('gap below stop does not assume fill at stop price', () => {
  const s = sample(); s.bars[22].open = 90; s.bars[22].low = 89;
  const r = calc(s); assert.equal(r.exit, 90); assert.ok(Math.abs(r.net + 10.2) < 1e-9);
});
test('intraday stop takes precedence over later recovery', () => {
  const s = sample(); s.bars[22].low = 94; s.bars[22].close = 106; s.bars[22].high = 107;
  const r = calc(s); assert.equal(r.exit, 95); assert.ok(Math.abs(r.net + 5.2) < 1e-9);
});
test('three observation days exclude entry day', () => {
  const s = sample(); s.bars[24].close = 104; s.bars[24].high = 105;
  const r = calc(s); assert.equal(r.exitDate, s.bars[24].date); assert.ok(Math.abs(r.net - 3.8) < 1e-9);
});
test('immature horizon stays pending even after an early stop', () => {
  const s = sample(); s.bars = s.bars.slice(0, 23); s.bars[22].low = 94;
  assert.equal(calc(s).status, 'pending');
});
test('one-price entry is not assumed executable', () => {
  const s = sample(); s.bars[21] = { ...s.bars[21], open: 110, close: 110, low: 110, high: 110 };
  assert.equal(calc(s).status, 'no_fill');
});
test('unexecutable stop waits for next tradable opening', () => {
  const s = sample(); s.bars[22] = { ...s.bars[22], open: 90, close: 90, low: 90, high: 90 }; s.bars[23].open = 88; s.bars[23].low = 87;
  const r = calc(s); assert.equal(r.exitDate, s.bars[23].date); assert.equal(r.exit, 88);
});
test('missing market session is blocked, not counted as another holding day', () => {
  const s = sample(), calendar = s.bars.map(x => x.date); s.bars.splice(22, 1);
  assert.equal(simulate(s, 20, options, calendar).status, 'blocked');
});
test('unexecutable expiry does not fabricate closing sale', () => {
  const s = sample(); s.bars[24] = { ...s.bars[24], open: 100, close: 100, low: 100, high: 100 };
  assert.equal(calc(s).status, 'blocked');
});
test('zero signals have unavailable, not zero-percent, performance', () => {
  const s = sample(); const r = runStudy({ stocks: [s], start: '2026-01-01', cutoff: '2026-01-27' }, { ...options, volume: 1000 });
  assert.equal(r.count, 0); assert.equal(r.winRate, null); assert.equal(r.avg, null);
});

test('date comparison separates signal, next-session entry and first sale day', () => {
  const s = sample(), data = { stocks: [s], start: '2026-01-01', cutoff: '2026-01-27' };
  const r = dateSnapshot(data, '2026-01-21', options);
  assert.equal(r.entryDate, '2026-01-22'); assert.equal(r.sellDate, '2026-01-23');
  assert.equal(r.rows[0].f.vr, 2); assert.equal(r.rows[0].entryFeatures.vr, 100 / 120);
  s.bars[22].volume = 1e9;
  assert.equal(dateSnapshot(data, '2026-01-21', options).rows[0].hit, true);
  assert.equal(dateSnapshot(data, '2026-01-21', options).rows[0].f.vr, 2);
});
test('missing observation day does not fall forward to a different stock bar', () => {
  const a = sample(), b = sample(); b.code = '600001'; a.bars.splice(21, 1);
  const r = dateSnapshot({ stocks: [a, b], start: '2026-01-01', cutoff: '2026-01-27' }, '2026-01-21', options);
  assert.equal(r.entryDate, '2026-01-22'); assert.equal(r.rows.find(x => x.stock.code === a.code).entry, undefined);
});
test('latest date leaves future prices unknown and non-trading date is explicit', () => {
  const data = { stocks: [sample()], start: '2026-01-01', cutoff: '2026-01-27' };
  const r = dateSnapshot(data, '2026-01-27', options);
  assert.equal(r.entryDate, undefined); assert.equal(r.rows[0].entry, undefined);
  assert.equal(dateSnapshot(data, '2026-02-01', options).isObservedDate, false);
  assert.equal(reviewDates({ ...data, cutoff: '2026-01-20' }).length, 20);
});
