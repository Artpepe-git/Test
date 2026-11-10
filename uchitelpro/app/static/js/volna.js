(function () {
  var clock = document.getElementById("clock");
  function tick() {
    if (!clock) return;
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    clock.textContent = d.getDate() + "/" + (d.getMonth() + 1) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  tick(); setInterval(tick, 20000);
  var btn = document.getElementById("theme");
  if (btn) btn.addEventListener("click", function () {
    var root = document.documentElement, green = root.getAttribute("data-theme") === "green";
    if (green) root.removeAttribute("data-theme"); else root.setAttribute("data-theme", "green");
    try { localStorage.setItem("volna-theme", green ? "dark" : "green"); } catch (e) {}
  });
})();
