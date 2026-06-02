// Palette selection + click-to-paint for the member calendar. The only custom
// JS in the app: it tracks the active type and posts day clicks via HTMX.
(function () {
  let selectedType = "pto";

  document.addEventListener("click", function (e) {
    const chip = e.target.closest(".chip[data-type]");
    if (chip) {
      selectedType = chip.dataset.type;
      document.querySelectorAll(".chip[data-type]").forEach(function (c) {
        c.classList.toggle("sel", c === chip);
      });
      return;
    }
    const cell = e.target.closest("td.day[data-date]");
    if (!cell) return;
    const cal = document.getElementById("calendar");
    const memberId = cal.dataset.member;
    const month = cal.dataset.month;
    const notesEl = document.getElementById("cal-notes");
    const notes = notesEl ? notesEl.value : "";
    const clearing = cell.dataset.type === selectedType;
    const url = clearing
      ? "/members/" + memberId + "/timeoff/clear"
      : "/members/" + memberId + "/timeoff";
    const values = clearing
      ? { date: cell.dataset.date, month: month }
      : { date: cell.dataset.date, type: selectedType, notes: notes, month: month };
    htmx.ajax("POST", url, { target: "#calendar", swap: "outerHTML", values: values });
  });
})();
