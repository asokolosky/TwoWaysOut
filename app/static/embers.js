// Decorative ember particles behind the landing hero.
// Draws on <canvas data-embers aria-hidden="true">. Pauses when the tab is hidden and
// draws nothing when the user prefers reduced motion.
(function () {
  "use strict";

  var canvas = document.querySelector("canvas[data-embers]");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var motion = window.matchMedia("(prefers-reduced-motion: reduce)");

  var embers = [];
  var width = 0;
  var height = 0;
  var rafId = 0;
  var lastTime = 0;

  function targetCount() {
    if (width < 480) return 12;
    if (width < 768) return 20;
    return 32;
  }

  function spawn(atRandomHeight) {
    return {
      x: Math.random() * width,
      y: atRandomHeight ? Math.random() * height : height + 10,
      r: 0.8 + Math.random() * 1.8,
      vy: 10 + Math.random() * 22,     // px per second, upward
      drift: (Math.random() - 0.5) * 8, // px per second, sideways
      phase: Math.random() * Math.PI * 2,
      life: 0,
      maxLife: 5 + Math.random() * 6,  // seconds
      hue: 18 + Math.random() * 18,    // orange to red-orange
    };
  }

  function resize() {
    var rect = canvas.getBoundingClientRect();
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var n = targetCount();
    while (embers.length < n) embers.push(spawn(true));
    embers.length = n;
  }

  function step(time) {
    var dt = Math.min((time - lastTime) / 1000 || 0, 0.05);
    lastTime = time;
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = "lighter";

    for (var i = 0; i < embers.length; i++) {
      var e = embers[i];
      e.life += dt;
      e.y -= e.vy * dt;
      e.x += (e.drift + Math.sin(e.phase + e.life * 1.3) * 6) * dt;
      if (e.life > e.maxLife || e.y < -10) {
        embers[i] = spawn(false);
        continue;
      }
      // Fade in quickly, fade out over the rest of the life.
      var t = e.life / e.maxLife;
      var alpha = (t < 0.15 ? t / 0.15 : 1 - (t - 0.15) / 0.85) * 0.55;
      var glow = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, e.r * 4);
      glow.addColorStop(0, "hsla(" + e.hue + ", 100%, 65%, " + alpha + ")");
      glow.addColorStop(1, "hsla(" + e.hue + ", 100%, 50%, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.r * 4, 0, Math.PI * 2);
      ctx.fill();
    }
    rafId = requestAnimationFrame(step);
  }

  function start() {
    if (rafId || motion.matches || document.visibilityState === "hidden") return;
    lastTime = performance.now();
    rafId = requestAnimationFrame(step);
  }

  function stop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  function sync() {
    if (motion.matches) {
      stop();
      ctx.clearRect(0, 0, width, height);
    } else if (document.visibilityState === "hidden") {
      stop();
    } else {
      start();
    }
  }

  resize();
  var resizeTimer = 0;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 150);
  });
  document.addEventListener("visibilitychange", sync);
  if (motion.addEventListener) motion.addEventListener("change", sync);
  sync();
})();
