document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const csrf = document.querySelector('meta[name="csrf-token"]');
  if (!csrf) return;
  if (form.querySelector('input[name="csrf_token"]')) return;
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = "csrf_token";
  input.value = csrf.getAttribute("content") || "";
  form.appendChild(input);
});
