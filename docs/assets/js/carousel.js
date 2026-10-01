// Adds previous/next buttons to every [data-carousel]. Without this script the
// track still scrolls and snaps; only the buttons stay hidden.
document.querySelectorAll('[data-carousel]').forEach((carousel) => {
  const track = carousel.querySelector('.track');
  const nav = carousel.querySelector('.carousel-nav');
  const prev = nav.querySelector('.prev');
  const next = nav.querySelector('.next');
  const step = () => track.querySelector('.slide').offsetWidth + parseFloat(getComputedStyle(track).columnGap);

  const max = () => track.scrollWidth - track.clientWidth;
  // Where the current smooth scroll is heading, so quick repeated clicks add up
  // instead of each one starting from a mid-animation position.
  let target = null;

  const update = () => {
    const at = target ?? track.scrollLeft;
    prev.disabled = at < 4;
    next.disabled = at > max() - 4;
  };

  const go = (direction) => {
    const from = target ?? track.scrollLeft;
    const index = Math.round(from / step()) + direction;
    target = Math.min(max(), Math.max(0, index * step()));
    track.scrollTo({ left: target });
    update();
  };

  prev.addEventListener('click', () => go(-1));
  next.addEventListener('click', () => go(1));
  track.addEventListener('scroll', () => {
    if (target !== null && Math.abs(track.scrollLeft - target) < 2) target = null;
    update();
  }, { passive: true });
  // A swipe or trackpad scroll takes over from any pending button target.
  ['wheel', 'touchstart', 'keydown'].forEach((type) =>
    track.addEventListener(type, () => { target = null; }, { passive: true }));
  window.addEventListener('resize', update);
  nav.hidden = false;
  update();
});
