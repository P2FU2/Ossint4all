/* Helpers mínimos do painel */
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-confirm]");
  if (!el) return;
  const msg = el.getAttribute("data-confirm") || "Confirmar ação?";
  if (!window.confirm(msg)) {
    ev.preventDefault();
    ev.stopImmediatePropagation();
  }
});
