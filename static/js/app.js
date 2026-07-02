// WorldCupPredict — client-side interactivity
(() => {
  'use strict';

  // Animate confidence values on load
  document.querySelectorAll('.confidence-badge').forEach(badge => {
    const text = badge.textContent.trim();
    const match = text.match(/(\d+)/);
    if (!match) return;
    const target = parseInt(match[1], 10);
    const suffix = text.includes('%') ? '% 置信度' : '% Confidence';
    let current = 0;
    const step = Math.max(1, Math.ceil(target / 30));
    badge.textContent = `0${suffix}`;
    const interval = setInterval(() => {
      current = Math.min(target, current + step);
      badge.textContent = `${current}${suffix}`;
      if (current >= target) clearInterval(interval);
    }, 30);
  });

  // Animate probability bars
  document.querySelectorAll('.market-prob-bar').forEach(bar => {
    const segments = bar.querySelectorAll('div');
    segments.forEach(seg => {
      const finalWidth = seg.style.width;
      seg.style.width = '0%';
      seg.style.transition = 'width 0.8s cubic-bezier(0.25,0.46,0.45,0.94)';
      requestAnimationFrame(() => {
        seg.style.width = finalWidth;
      });
    });
  });

  // Add hover reveal for commentator quotes (mobile tap)
  document.querySelectorAll('.commentator-quote').forEach(quote => {
    quote.addEventListener('click', function() {
      this.classList.toggle('expanded');
    });
  });

  console.log('%c⚽ WorldCupPredict %cAI Prediction Engine',
    'color:#d4a853;font-size:16px;', 'color:#8b949e;');
})();
