// Field Notes TOC scrollspy — highlight the anchor closest to the
// reading position. Vanilla, ~30 lines, no library.

const links = Array.from(document.querySelectorAll(".fn-toc-list a[data-toc-target]"));
const targets = links
  .map((link) => {
    const id = link.getAttribute("data-toc-target");
    const el = id ? document.getElementById(id) : null;
    return el ? { link, el } : null;
  })
  .filter((entry) => entry !== null);

if (targets.length > 0) {
  const setActive = (activeEl) => {
    for (const { link, el } of targets) {
      link.parentElement.classList.toggle("is-active", el === activeEl);
    }
  };

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.target.offsetTop - b.target.offsetTop);
      if (visible.length > 0) setActive(visible[0].target);
    },
    { rootMargin: "-20% 0px -70% 0px", threshold: 0 },
  );

  for (const { el } of targets) observer.observe(el);
}
