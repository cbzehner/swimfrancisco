// Horizon-picker combobox: an ARIA menu (role="menu" / menuitemradio) with
// open/close state, positioning, and full keyboard navigation. Extracted from
// status.js, which owns the horizon domain logic (options, labels, applying a
// selection) and drives this widget through the small interface below.

export function initHorizonMenu(control, { onSelect, refresh } = {}) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = document.querySelector("[data-horizon-menu]");
  if (!button || !menu) return null;

  function items() {
    return Array.from(menu.querySelectorAll("button[role='menuitemradio']"));
  }

  function closeMenu() {
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
  }

  function closeMenuAndFocusButton() {
    closeMenu();
    button.focus();
  }

  function positionMenu() {
    const rect = button.getBoundingClientRect();
    const top = rect.bottom + 4;
    const isMobile = window.matchMedia("(max-width: 640px)").matches;
    const left = isMobile ? 16 : rect.left;
    const width = isMobile ? window.innerWidth - 32 : Math.max(rect.width, 256);
    const root = document.documentElement.style;
    root.setProperty("--horizon-menu-top", `${Math.round(top)}px`);
    root.setProperty("--horizon-menu-left", `${Math.round(left)}px`);
    root.setProperty("--horizon-menu-width", `${Math.round(width)}px`);
  }

  function openMenu() {
    menu.hidden = false;
    positionMenu();
    button.setAttribute("aria-expanded", "true");
  }

  function focusMenuItem(direction = 1) {
    const list = items();
    if (!list.length) return;
    const checkedIndex = list.findIndex((item) => item.getAttribute("aria-checked") === "true");
    const targetIndex = checkedIndex >= 0 ? checkedIndex : direction < 0 ? list.length - 1 : 0;
    list[targetIndex].focus();
  }

  function focusAdjacentItem(direction) {
    const list = items();
    if (!list.length) return;
    const currentIndex = list.indexOf(document.activeElement);
    const nextIndex = currentIndex < 0
      ? direction < 0 ? list.length - 1 : 0
      : (currentIndex + direction + list.length) % list.length;
    list[nextIndex].focus();
  }

  function selectItem(id, source) {
    onSelect(id, source);
    closeMenuAndFocusButton();
  }

  function activateFocusedItem() {
    const item = document.activeElement;
    if (!item || item.getAttribute("role") !== "menuitemradio" || !item.value) return;
    selectItem(item.value, "keyboard");
  }

  function toggleMenu() {
    if (menu.hidden) {
      openMenu();
      focusMenuItem();
    } else {
      closeMenu();
    }
  }

  function render({ buttonLabel, items: itemData }) {
    button.textContent = buttonLabel;
    menu.replaceChildren(
      ...itemData.map((item) => {
        const el = document.createElement("button");
        el.type = "button";
        el.setAttribute("role", "menuitemradio");
        el.value = item.id;
        el.textContent = item.label;
        el.setAttribute("aria-checked", String(item.selected));
        el.addEventListener("click", () => selectItem(item.id, "click"));
        return el;
      }),
    );
  }

  button.addEventListener("click", () => {
    refresh();
    toggleMenu();
  });

  button.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    refresh();
    openMenu();
    focusMenuItem(event.key === "ArrowUp" ? -1 : 1);
  });

  document.addEventListener("click", (event) => {
    if (control.contains(event.target)) return;
    if (menu.contains(event.target)) return;
    closeMenu();
  });

  // Close on Tab-out so an open menu doesn't strand the user with focus
  // somewhere unrelated on the page. focusout fires when any element inside
  // the button or menu loses focus; relatedTarget is who's gaining it.
  // Only close when focus lands on a keyboard-reachable element
  // (tabIndex >= 0): WebKit doesn't focus <button>s on tap — it moves focus
  // to the nearest tabindex ancestor instead, which here is the skip-link
  // target <main tabindex="-1"> — so an iOS tap on a menu item looked like
  // Tab-out and closed the menu before the tap's click could land on the
  // item. A real Tab always stops on tabIndex >= 0. Outside-tap closing is
  // owned by the document click listener above.
  document.addEventListener("focusout", (event) => {
    if (menu.hidden) return;
    const next = event.relatedTarget;
    if (!next || next.tabIndex < 0) return;
    if (control.contains(next) || menu.contains(next)) return;
    closeMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (menu.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenuAndFocusButton();
      return;
    }
    if (!menu.contains(document.activeElement)) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusAdjacentItem(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusAdjacentItem(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      items()[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items().at(-1)?.focus();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateFocusedItem();
    }
  });

  window.addEventListener("resize", () => {
    if (button.getAttribute("aria-expanded") === "true") positionMenu();
  });

  window.addEventListener("scroll", () => {
    if (button.getAttribute("aria-expanded") === "true") positionMenu();
  });

  return { render };
}
