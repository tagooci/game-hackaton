import './assistant.css';

type Page = { title: string; text: string; label: string };

/** Presentation only: all assessment facts come from the server. */
export function createScenarioAssistant(host: HTMLElement, onOpen = () => {}) {
  const root = document.createElement('aside');
  root.className = 'scenario-assistant';
  root.hidden = true;
  root.setAttribute('aria-label', 'Дорожный помощник');
  root.innerHTML = `<section class="assistant-bubble" role="dialog" aria-label="Реплика дорожного помощника">
    <div class="assistant-eyebrow">ДОРОЖНЫЙ ПОМОЩНИК</div>
    <button class="assistant-close" type="button" aria-label="Свернуть реплику">×</button>
    <div class="assistant-message" role="status" aria-live="polite" aria-atomic="true"><h2></h2><p></p><span class="assistant-label"></span></div>
    <footer><span class="assistant-page"></span><button class="assistant-next" type="button">Дальше →</button></footer>
  </section><button class="assistant-avatar" type="button" aria-label="Открыть реплику дорожного помощника" aria-expanded="false"><img src="/assistant/robot.svg" alt="Робот — дорожный помощник" draggable="false"><span>Дорожный помощник</span></button>`;
  host.append(root);
  const bubble = root.querySelector<HTMLElement>('.assistant-bubble')!;
  const avatar = root.querySelector<HTMLButtonElement>('.assistant-avatar')!;
  const next = root.querySelector<HTMLButtonElement>('.assistant-next')!;
  const title = root.querySelector('h2')!;
  const text = root.querySelector('p')!;
  const label = root.querySelector<HTMLElement>('.assistant-label')!;
  const pagination = root.querySelector<HTMLElement>('.assistant-page')!;
  let pages: Page[] = [];
  let page = 0;
  let opened = false;
  function setOpen(value: boolean) {
    opened = value;
    bubble.hidden = !value;
    avatar.setAttribute('aria-expanded', String(value));
    if (value) onOpen();
  }
  function render() {
    const current = pages[page];
    if (!current) return;
    title.textContent = current.title;
    text.textContent = current.text;
    label.textContent = current.label;
    pagination.textContent = `${page + 1} / ${pages.length}`;
    next.textContent = page === pages.length - 1 ? 'Понятно ✓' : 'Дальше →';
  }
  function show(value: Page[]) {
    pages = value; page = 0; root.hidden = false; render(); setOpen(true);
  }
  avatar.onclick = () => setOpen(!opened);
  root.querySelector<HTMLButtonElement>('.assistant-close')!.onclick = () => { setOpen(false); avatar.focus(); };
  next.onclick = () => { if (page < pages.length - 1) { page++; render(); } else { setOpen(false); avatar.focus(); } };
  root.onkeydown = event => { if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); avatar.focus(); } };
  return {
    get isOpen() { return opened; },
    introduction(role: string | null) {
      show([{ title: 'Начинаем проезд', text: role === 'left-turn'
        ? 'Ваша задача — повернуть налево и остановиться в своей финишной зоне. Оцените обстановку и выберите безопасный момент для манёвра.'
        : 'Ваша задача — проехать прямо и остановиться в своей финишной зоне. Следите за обстановкой на перекрёстке.', label: 'Закройте реплику и нажмите на игру, чтобы начать движение' }]);
    },
    result(result: string) {
      show([{ title: 'Разберём ваш проезд', text: result, label: 'Результат проверки сервера' },
        { title: 'Можно продолжать', text: 'Нажмите на персонажа, если захотите снова прочитать разбор. Закройте реплику и нажмите на игру, чтобы вернуться к управлению.', label: 'Помощник остаётся рядом' }]);
    },
    hide() { setOpen(false); root.hidden = true; },
    dispose() { root.remove(); },
  };
}

/** Offline visual reference; no multiplayer session or generated assessment. */
export function showAssistantPreview(host: HTMLElement) {
  host.innerHTML = `<div class="assistant-preview"><div class="assistant-preview-sky"></div><div class="assistant-preview-road"></div><header><b>АВТОГОРОД</b><span>Перекрёсток · макет помощника</span></header><div class="assistant-preview-controls"><button data-preview="intro">Начало сценария</button><button data-preview="success">Успешный проезд</button><button data-preview="violation">Нарушение</button></div><div class="assistant-preview-note">Просмотр интерфейса · данные примера</div></div>`;
  const assistant = createScenarioAssistant(host);
  host.querySelector<HTMLButtonElement>('[data-preview="intro"]')!.onclick = () => assistant.introduction('left-turn');
  host.querySelector<HTMLButtonElement>('[data-preview="success"]')!.onclick = () => assistant.result('Проезд выполнен правильно');
  host.querySelector<HTMLButtonElement>('[data-preview="violation"]')!.onclick = () => assistant.result('Нарушение: не уступили встречному автомобилю');
  assistant.result('Проезд выполнен правильно');
  return () => { assistant.dispose(); host.replaceChildren(); };
}

