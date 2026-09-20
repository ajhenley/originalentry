// Zooming a document image (S2.1, T10.3).
//
// Progressive enhancement: without this file the image is still there, still scrollable, and the
// text alternative below it still says everything the image says. With it, the document can be
// enlarged by button or by key, which is what reading a scanned invoice actually needs.

const STEPS = [0.5, 0.75, 1, 1.5, 2, 3, 4];

function setUp(figure) {
  const image = figure.querySelector("[data-zoom-image]");
  const level = figure.querySelector("[data-zoom-level]");
  const region = figure.querySelector("[role='region']");
  if (!image) return;

  let index = STEPS.indexOf(1);

  function apply() {
    const scale = STEPS[index];
    image.style.transform = `scale(${scale})`;
    if (level) level.textContent = `${Math.round(scale * 100)}%`;
  }

  function move(by) {
    index = Math.max(0, Math.min(STEPS.length - 1, index + by));
    apply();
  }

  figure.querySelector("[data-zoom-in]")?.addEventListener("click", () => move(1));
  figure.querySelector("[data-zoom-out]")?.addEventListener("click", () => move(-1));
  figure.querySelector("[data-zoom-reset]")?.addEventListener("click", () => {
    index = STEPS.indexOf(1);
    apply();
  });

  region?.addEventListener("keydown", (event) => {
    if (event.key === "+" || event.key === "=") move(1);
    else if (event.key === "-") move(-1);
    else if (event.key === "0") { index = STEPS.indexOf(1); apply(); }
    else return;
    event.preventDefault();
  });

  apply();
}

document.querySelectorAll("[data-zoom]").forEach(setUp);
