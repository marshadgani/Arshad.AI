import { below, atLeast } from './styles/breakpoints';
import { setViewport } from './setupTests';

// Self-test for the test harness itself. Without this, a matchMedia stub
// that ignores its query string would make every "mobile" test pass on a
// desktop-width viewport too — a silently vacuous test surface.
describe('setupTests: setViewport', () => {
  it('flips below("mobile") and atLeast("tablet") at a mobile width', () => {
    setViewport(375);
    expect(window.matchMedia(below('mobile')).matches).toBe(true);
    expect(window.matchMedia(atLeast('tablet')).matches).toBe(false);
  });

  it('flips them the other way at a desktop width', () => {
    setViewport(1280);
    expect(window.matchMedia(below('mobile')).matches).toBe(false);
    expect(window.matchMedia(atLeast('tablet')).matches).toBe(true);
  });
});
